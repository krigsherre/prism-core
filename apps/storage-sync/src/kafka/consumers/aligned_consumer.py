import asyncio
import json
import datetime
from typing import Dict, Any
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from repositories.sql_repo import SQLRepository
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential
from opentelemetry import trace
from opentelemetry.propagate import extract

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

class AlignedSQLConsumer:
    def __init__(self, sql_repo: SQLRepository) -> None:
        self.sql_repo = sql_repo
        self._consumer = None
        self.dlq_producer = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "aligned_sql_payloads",
            bootstrap_servers=settings.kafka_broker,
            group_id=settings.kafka_consumer_group_aligned,
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        self.dlq_producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect_kafka()
            await self.dlq_producer.start()
        except Exception as e:
            logger.error("Failed to connect AlignedSQLConsumer to Kafka", error=str(e))
            return
            
        logger.info("AlignedSQLConsumer started...")
        
        try:
            async for msg in self._consumer:
                await self._process_message(msg)
        except asyncio.CancelledError:
            logger.info("Aligned Consumer cancelled")
        except Exception as e:
            logger.error("Aligned Consumer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self.dlq_producer:
                await self.dlq_producer.stop()

    async def _process_message(self, msg) -> None:
        if not msg.value:
            return
            
        headers_dict = {k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in (msg.headers or [])}
        ctx = extract(headers_dict)
        
        with tracer.start_as_current_span("process_aligned_payload", context=ctx):
            payload = None
            try:
                payload = json.loads(msg.value.decode("utf-8"))
                await self._process_payload_with_retry(payload)
                await self._consumer.commit()
            except json.JSONDecodeError:
                logger.error("Failed to decode JSON", offset=msg.offset)
                await self._consumer.commit()
            except Exception as e:
                logger.error("Exhausted retries, routing to DLQ", error=str(e))
                await self._route_to_dlq(e, payload)
                await self._consumer.commit()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _process_payload_with_retry(self, payload: Dict[str, Any]) -> None:
        document_id = payload.get("document_id")
        tenant_id = payload.get("tenant_id")
        target_table = payload.get("target_table")
        mapping_status = payload.get("mapping_status")
        
        if not document_id or not tenant_id or not target_table:
            raise ValueError("Missing required fields (document_id, tenant_id, target_table)")
            
        row_id = payload.get("row_id")
        
        if row_id:
            await self.sql_repo.update_aligned_table(
                row_id=row_id,
                mapping_status=mapping_status,
                strict_columns=payload.get("strict_columns", {}),
                unmapped_jsonb=payload.get("unmapped_jsonb", {}),
                target_table=target_table,
                user_id=payload.get("user_id"),
                source_page=payload.get("source_page"),
                source_bbox=payload.get("source_bbox")
            )
            logger.info("Updated aligned table in SQL", target_table=target_table, mapping_status=mapping_status, row_id=row_id)
        else:
            await self.sql_repo.insert_aligned_rows(
                tenant_id=tenant_id,
                document_id=document_id,
                node_id=payload.get("node_id", "unknown"),
                target_table=target_table,
                mapping_status=mapping_status,
                strict_columns_list=payload.get("strict_columns", []),
                unmapped_jsonb_list=payload.get("unmapped_jsonb", []),
                user_id=payload.get("user_id"),
                source_page=payload.get("source_page"),
                source_bbox=payload.get("source_bbox")
            )
            logger.info("Inserted aligned rows into SQL", target_table=target_table, mapping_status=mapping_status)
            
        await self._emit_node_completed_status(document_id, tenant_id)

    async def _emit_node_completed_status(self, document_id: str, tenant_id: str) -> None:
        if not self.dlq_producer:
            return
            
        status_payload = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "sql_node_completed": True,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        try:
            await self.dlq_producer.send_and_wait(
                "document_status_events",
                json.dumps(status_payload).encode("utf-8"),
                key=tenant_id.encode("utf-8")
            )
        except Exception as e:
            logger.error(f"Failed to emit status: {e}")

    async def _route_to_dlq(self, e: Exception, payload: dict) -> None:
        if not self.dlq_producer:
            return
            
        doc_id = payload.get("document_id", "unknown") if isinstance(payload, dict) else "unknown"
        filename = payload.get("metadata", {}).get("original_filename", "unknown") if isinstance(payload, dict) else "unknown"
        t_id = payload.get("tenant_id", "unknown").encode("utf-8") if isinstance(payload, dict) else b"unknown"
        
        fail_payload = {
            "document_id": doc_id,
            "tenant_id": t_id.decode("utf-8"),
            "filename": filename,
            "current_stage": "storage-sync",
            "status": "FAILED",
            "error_message": str(e),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        dlq_msg = {
            "tenant_id": t_id.decode("utf-8"),
            "document_id": doc_id,
            "source": "aligned-sql-consumer",
            "error": str(e),
            "payload": payload
        }
        
        try:
            await self.dlq_producer.send_and_wait("document_status_events", json.dumps(fail_payload).encode("utf-8"), key=t_id)
            await self.dlq_producer.send_and_wait("system_dlq", value=json.dumps(dlq_msg).encode("utf-8"))
        except Exception as status_e:
            logger.error(f"Failed to emit DLQ events: {status_e}")