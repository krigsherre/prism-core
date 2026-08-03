# pyright: reportAttributeAccessIssue=false
import asyncio
import os
import tempfile
import structlog
import traceback
import json
import datetime
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from opentelemetry import trace
from opentelemetry.propagate import extract

import proto.prism.v1.events_pb2 as events_pb2

from core.service import ExtractionService
from core.dom.chunker import SmartChunker
from config.settings import settings

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

class DocumentSlotRegistry:
    """
    Per-document fairness guard.
    Caps how many concurrent slots a single document_id can hold so that
    a large fan-out cannot starve other documents waiting on the global semaphore.
    """
    def __init__(self, max_per_doc: int):
        self._max = max_per_doc
        self._lock = asyncio.Lock()
        self._counts: dict[str, int] = {}
        self._waiters: dict[str, asyncio.Condition] = {}

    async def acquire(self, doc_id: str) -> None:
        async with self._lock:
            if doc_id not in self._waiters:
                self._waiters[doc_id] = asyncio.Condition(self._lock)
        cond = self._waiters[doc_id]
        async with cond:
            while self._counts.get(doc_id, 0) >= self._max:
                await cond.wait()
            self._counts[doc_id] = self._counts.get(doc_id, 0) + 1

    async def release(self, doc_id: str) -> None:
        cond = self._waiters.get(doc_id)
        if cond:
            async with cond:
                self._counts[doc_id] = max(0, self._counts.get(doc_id, 1) - 1)
                cond.notify_all()


class KafkaConsumerService:
    def __init__(self, extraction_service: ExtractionService, max_concurrent: int = 4):
        self.extraction_service = extraction_service
        self._max_concurrent = max_concurrent
        self.processing_semaphore = asyncio.Semaphore(max_concurrent)
        self._doc_slots = DocumentSlotRegistry(max_per_doc=max(1, max_concurrent // 2))
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None
        self._task = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _connect_kafka(self):
        if self.producer:
            await self.producer.start()
        if self.consumer:
            await self.consumer.start()

    async def start(self):
        self.consumer = AIOKafkaConsumer(
            "gpu_processing_queue",
            bootstrap_servers=settings.kafka_broker,
            group_id="gpu_extractor_group",
            session_timeout_ms=45000,
            heartbeat_interval_ms=10000,
            max_poll_interval_ms=600000,
            auto_offset_reset="earliest",
        )
        self.producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect to Kafka, continuing in degraded mode.", error=str(e))
            return
            
        logger.info("GPU Extractor consuming from gpu_processing_queue...")
        self._task = asyncio.create_task(self._consume_loop())

    async def _consume_loop(self):
        """
        Backpressure-aware consume loop.
        We only spawn a new task once there is a free semaphore slot, which
        prevents unbounded task accumulation when the pipeline is saturated.
        """
        try:
            if self.consumer:
                async for msg in self.consumer:
                    await self.processing_semaphore.acquire()
                    asyncio.create_task(self._process_message_with_slot(msg))
        except asyncio.CancelledError:
            pass

    async def _process_message_with_slot(self, msg):
        """Wrapper that owns the already-acquired semaphore slot."""
        try:
            await self._process_message(msg)
        finally:
            self.processing_semaphore.release()

    async def stop(self):
        if self._task:
            self._task.cancel()
        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()


    async def _process_message(self, msg):
        structlog.contextvars.clear_contextvars()

        event = self._parse_ingest_event(msg)
        if not event:
            return

        doc_id = event.event_id

        headers = {}
        if hasattr(msg, 'headers') and msg.headers:
            for k, v in msg.headers:
                headers[k] = v.decode("utf-8") if v else ""
        ctx = extract(headers)

        with tracer.start_as_current_span("process_kafka_message", context=ctx) as span:
            span.set_attribute("tenant_id", event.tenant_id)
            span.set_attribute("event_id", doc_id)

            structlog.contextvars.bind_contextvars(
                tenant_id=event.tenant_id, event_id=doc_id
            )
            logger.info("Received Kafka message", length=len(msg.value))

            await self._doc_slots.acquire(doc_id)
            try:
                await self._publish_status(event, "EXTRACTING")
                await self._route_event(event)
            except Exception as e:
                logger.error("Extraction pipeline failed", error=str(e))
                logger.debug(traceback.format_exc())
                await self._publish_status(event, "FAILED", error_message=str(e))
                await self._route_to_dlq(msg, event)
            finally:
                await self._doc_slots.release(doc_id)

    def _parse_ingest_event(self, msg) -> Optional[events_pb2.IngestEvent]:
        event = events_pb2.IngestEvent()
        try:
            event.ParseFromString(msg.value)
            return event
        except Exception as e:
            try:
                data = json.loads(msg.value.decode("utf-8"))
                event.event_id = data.get("event_id", "")
                event.tenant_id = data.get("tenant_id", "")
                event.s3_uri = data.get("s3_uri", "")
                event.file_hash_sha256 = data.get("file_hash_sha256", "")
                event.timestamp = data.get("timestamp", "")
                
                if "metadata" in data and isinstance(data["metadata"], dict):
                    for k, v in data["metadata"].items():
                        event.metadata[k] = str(v)
                return event
            except Exception as json_e:
                logger.error("Failed to parse IngestEvent", proto_error=str(e), json_error=str(json_e))
                return None

    async def _publish_status(self, event: events_pb2.IngestEvent, status: str, error_message: str = ""):
        if not self.producer:
            return
            
        metadata = dict(event.metadata) if event and hasattr(event, "metadata") else {}
        document_id = event.event_id if event else "unknown"
        filename = metadata.get("original_filename", "unknown")
        tenant = event.tenant_id if event else "unknown"
        
        status_event = {
            "document_id": document_id,
            "tenant_id": tenant,
            "filename": filename,
            "current_stage": "gpu-extractor",
            "status": status,
            "error_message": error_message,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        try:
            await self.producer.send_and_wait(
                "document_status_events",
                json.dumps(status_event).encode("utf-8"),
                key=tenant.encode("utf-8")
            )
        except Exception as status_e:
            logger.error(f"Failed to emit status: {status_e}")

    async def _route_to_dlq(self, msg, event: events_pb2.IngestEvent):
        if not self.producer:
            return
            
        try:
            tenant_key = event.tenant_id.encode("utf-8") if event else b"unknown"
            await self.producer.send_and_wait(
                "gpu_processing_dlq",
                msg.value,
                key=tenant_key,
            )
            logger.info("Sent failed message to DLQ")
        except Exception as dlq_e:
            logger.error(f"Failed to send to DLQ: {dlq_e}")

    async def _route_event(self, event: events_pb2.IngestEvent):
        metadata = dict(event.metadata)
        document_id = event.event_id
        
        if "start_page" not in metadata:
            await self._handle_orchestrator_mode(event, document_id, metadata)
        else:
            await self._handle_worker_mode(event, document_id, metadata)

    async def _handle_orchestrator_mode(self, event, document_id: str, metadata: dict):
        logger.info("Acting as Orchestrator. Calculating smart chunks...")
        
        path_parts = event.s3_uri.replace("s3://", "").split("/")
        bucket = path_parts[0]
        key = "/".join(path_parts[1:])
        
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(key)[1])
        os.close(tmp_fd)
        
        norm_path = None
        try:
            await asyncio.to_thread(self.extraction_service.s3.download_file, bucket, key, tmp_path)
            norm_path, directive = await asyncio.to_thread(self.extraction_service.preprocessor.preprocess, tmp_path)
            
            if directive == "PDF_LAYOUT":
                await self._fan_out_pdf_chunks(event, norm_path)
            else:
                await self._process_and_publish_entire_document(event, document_id, metadata)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            if norm_path and norm_path != tmp_path and os.path.exists(norm_path):
                os.remove(norm_path)

    async def _fan_out_pdf_chunks(self, event: events_pb2.IngestEvent, norm_path: str):
        chunks = SmartChunker.calculate_chunks(norm_path)
        chunk_total = len(chunks)

        if self.producer:
            for idx, chunk in enumerate(chunks):
                sub_event = events_pb2.IngestEvent()
                sub_event.CopyFrom(event)
                sub_event.metadata["start_page"] = str(chunk["start_page"])
                sub_event.metadata["end_page"] = str(chunk["end_page"])
                sub_event.metadata["chunk_index"] = str(idx)
                sub_event.metadata["chunk_total"] = str(chunk_total)

                if chunk["injected_context"]:
                    sub_event.metadata["injected_context"] = chunk["injected_context"]

                await self.producer.send_and_wait(
                    "gpu_processing_queue",
                    sub_event.SerializeToString(),
                    key=event.tenant_id.encode("utf-8"),
                )
            logger.info("Fanned out chunks to Kafka", num_chunks=chunk_total)

    async def _process_and_publish_entire_document(self, event: events_pb2.IngestEvent, document_id: str, metadata: dict):
        final_dom = await self.extraction_service.process_document(
            event.s3_uri, 
            document_id=document_id,
            metadata=metadata
        )
        if self.producer:
            await self.producer.send_and_wait(
                "parsed_documents",
                final_dom.SerializeToString(),
                key=event.tenant_id.encode("utf-8"),
            )

    async def _handle_worker_mode(self, event, document_id: str, metadata: dict):
        start_page = int(metadata["start_page"])
        end_page = int(metadata["end_page"])
        injected_context = metadata.get("injected_context", "")
        
        logger.info("Worker Mode processing chunk", start_page=start_page, end_page=end_page)
        
        final_dom = await self.extraction_service.process_document(
            event.s3_uri, 
            document_id=document_id,
            metadata=metadata,
            start_page=start_page,
            end_page=end_page,
            injected_context=injected_context
        )
        if self.producer:
            await self.producer.send_and_wait(
                "parsed_documents",
                final_dom.SerializeToString(),
                key=event.tenant_id.encode("utf-8"),
            )
            logger.info("Published parsed chunk DocumentDOM")