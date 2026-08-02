import asyncio
import json
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from datetime import datetime, timezone
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, Dict, Any, List

from core.alignment import WaterfallAlignmentStrategy
from config.settings import settings
from core.hitl_review import generate_hitl_review

tracer = trace.get_tracer(__name__)
logger = structlog.get_logger(__name__)

class SchemaCDCConsumer:
    def __init__(self, strategy: WaterfallAlignmentStrategy) -> None:
        self.strategy = strategy
        self._consumer: Optional[AIOKafkaConsumer] = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "schema_cdc",
            bootstrap_servers=settings.kafka_broker,
            group_id="schema-aligner-schema",
            auto_offset_reset="earliest"
        )
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect SchemaCDCConsumer to Kafka", error=str(e))
            return

        logger.info("SchemaCDCConsumer started listening", topic="schema_cdc")
        try:
            async for msg in self._consumer:
                with tracer.start_as_current_span("process_schema_cdc"):
                    if not msg.value:
                        continue
                    try:
                        payload = json.loads(msg.value.decode("utf-8"))
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode schema CDC payload")
                        continue

                    op = payload.get("payload", {}).get("op", "")
                    if op in ("c", "u"):
                        after = payload.get("payload", {}).get("after", {})
                        target_table = after.get("target_table")
                        columns = after.get("columns", [])
                        if target_table and columns:
                            self.strategy.update_schema(target_table, columns)
        except asyncio.CancelledError:
            logger.info("SchemaCDCConsumer cancelled")
        finally:
            if self._consumer:
                await self._consumer.stop()


class DictionaryCDCConsumer:
    def __init__(self, strategy: WaterfallAlignmentStrategy) -> None:
        self.strategy = strategy
        self._consumer: Optional[AIOKafkaConsumer] = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "dictionary_cdc",
            bootstrap_servers=settings.kafka_broker,
            group_id="schema-aligner-dictionary",
            auto_offset_reset="earliest"
        )
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect DictionaryCDCConsumer to Kafka", error=str(e))
            return

        logger.info("DictionaryCDCConsumer started listening", topic="dictionary_cdc")
        try:
            async for msg in self._consumer:
                with tracer.start_as_current_span("process_dictionary_cdc"):
                    if not msg.value:
                        continue
                    try:
                        payload = json.loads(msg.value.decode("utf-8"))
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode dictionary CDC payload")
                        continue

                    op = payload.get("payload", {}).get("op", "")
                    if op in ("c", "u"):
                        after = payload.get("payload", {}).get("after", {})
                        tenant_id = after.get("tenant_id")
                        target_table = after.get("target_table")
                        raw_label = after.get("raw_label")
                        mapped_column = after.get("mapped_column")

                        if tenant_id and target_table and raw_label and mapped_column:
                            self.strategy.update_synonym(tenant_id, target_table, raw_label, mapped_column)
        except asyncio.CancelledError:
            logger.info("DictionaryCDCConsumer cancelled")
        finally:
            if self._consumer:
                await self._consumer.stop()


class RawTableDOMConsumer:
    def __init__(self, strategy: WaterfallAlignmentStrategy) -> None:
        self.strategy = strategy
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_inferences)

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()
        if self._producer:
            await self._producer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "raw_table_doms",
            bootstrap_servers=settings.kafka_broker,
            group_id="schema-aligner-doms",
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect RawTableDOMConsumer to Kafka", error=str(e))
            return
            
        logger.info("RawTableDOMConsumer started listening", topic="raw_table_doms")
        
        try:
            async for msg in self._consumer:
                await self._handle_message(msg)
                await self._consumer.commit()
        except asyncio.CancelledError:
            logger.info("RawTableDOMConsumer cancelled")
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self._producer:
                await self._producer.stop()

    async def _handle_message(self, msg: Any) -> None:
        async with self.semaphore:
            headers_dict = {k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in (msg.headers or [])}
            ctx = extract(headers_dict)
            
            with tracer.start_as_current_span("process_raw_table_dom", context=ctx):
                if not msg.value:
                    return
                try:
                    data = json.loads(msg.value.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.warning("Failed to decode raw DOM payload")
                    return
                    
                await self._process_extracted_data(data, msg)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _align_with_retry(
        self,
        tenant_id: str,
        target_table: str,
        extracted_data: Dict[str, Any],
        markdown_content: str,
        parent_section_text: str,
        reflexion_error: str = "",
        previous_extraction: Optional[List[Dict[str, Any]]] = None,
        starting_attempt: int = 0,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
    ):
        return await self.strategy.align_with_reflexion(
            tenant_id,
            target_table,
            extracted_data,
            markdown_content,
            parent_section_text,
            reflexion_error=reflexion_error,
            previous_extraction=previous_extraction,
            starting_attempt=starting_attempt,
            few_shot_examples=few_shot_examples,
        )

    async def _process_extracted_data(self, data: Dict[str, Any], msg: Any) -> None:
        document_id = data.get("document_id", "unknown")
        tenant_id = data.get("tenant_id", "unknown")
        node_id = data.get("node_id", "unknown")
        target_table = data.get("target_table", "") or data.get("target_schema", "")
        extracted_data = data.get("extracted_data", {})
        markdown_content = data.get("markdown_content", "")
        parent_section_text = data.get("parent_section_text", "")
        reflexion_error = data.get("reflexion_error", "") or ""
        previous_extraction = data.get("previous_extraction")
        if isinstance(previous_extraction, dict):
            previous_extraction = [previous_extraction]
        starting_attempt = int(data.get("reflexion_attempt", 0) or 0)
        few_shot_examples = data.get("few_shot_examples") or []
        if not isinstance(few_shot_examples, list):
            few_shot_examples = []

        if not extracted_data and not markdown_content:
            logger.warning("Empty extracted_data and markdown in DOM payload", document_id=document_id)
            return

        await self._emit_status(document_id, data, "ALIGNING", reflexion_error or "")

        try:
            strict_columns, unmapped_jsonb, status, final_table, drifted_columns, reflexion_meta = (
                await self._align_with_retry(
                    tenant_id,
                    target_table,
                    extracted_data,
                    markdown_content,
                    parent_section_text,
                    reflexion_error=reflexion_error,
                    previous_extraction=previous_extraction,
                    starting_attempt=starting_attempt,
                    few_shot_examples=few_shot_examples,
                )
            )
        except Exception as e:
            logger.error("Critical failure during alignment, routing to DLQ", error=str(e), document_id=document_id)
            await self._emit_status(document_id, data, "FAILED", str(e))
            if self._producer:
                await self._producer.send_and_wait(
                    "schema_aligner_dlq",
                    key=document_id.encode("utf-8"),
                    value=json.dumps({
                        **data,
                        "mapping_status": "FAILED",
                        "unmapped_jsonb": [{"critic_error": str(e), "row_status": "FAILED"}],
                        "failure_class": "permanent",
                    }).encode("utf-8"),
                )
            return

        if not final_table:
            logger.error("Could not classify target table, saving as UNKNOWN_TABLE", document_id=document_id)
            final_table = "UNKNOWN_TABLE"

        if reflexion_meta and unmapped_jsonb:
            if isinstance(unmapped_jsonb[0], dict):
                unmapped_jsonb[0]["reflexion_meta"] = reflexion_meta

        await self._publish_aligned_payload(
            document_id,
            tenant_id,
            node_id,
            final_table,
            status,
            strict_columns,
            unmapped_jsonb,
            data,
            reflexion_meta=reflexion_meta,
        )

        if drifted_columns or status in ("NEEDS_REVIEW", "FAILED_VERIFICATION"):
            await self._publish_anomalies(
                document_id, tenant_id, final_table, drifted_columns, data,
                strict_columns=strict_columns, unmapped_jsonb=unmapped_jsonb, status=status,
            )


    async def _emit_status(self, document_id: str, data: Dict[str, Any], status: str, error_message: str) -> None:
        if not self._producer:
            return
        try:
            tenant_id = data.get("tenant_id", "default-tenant")
            status_payload = {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "filename": data.get("metadata", {}).get("original_filename", "unknown"),
                "current_stage": "schema-aligner",
                "status": status,
                "error_message": error_message,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await self._producer.send_and_wait(
                "document_status_events",
                key=tenant_id.encode("utf-8"),
                value=json.dumps(status_payload).encode("utf-8")
            )
        except Exception as status_e:
            logger.error(f"Failed to emit status: {status_e}")

    async def _publish_aligned_payload(
        self,
        document_id: str,
        tenant_id: str,
        node_id: str,
        final_table: str,
        status: str,
        strict_columns: List[Dict[str, Any]],
        unmapped_jsonb: List[Dict[str, Any]],
        original_data: Dict[str, Any],
        reflexion_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._producer:
            return

        passed_strict: List[Dict[str, Any]] = []
        passed_unmapped: List[Dict[str, Any]] = []
        failed_strict: List[Dict[str, Any]] = []
        failed_unmapped: List[Dict[str, Any]] = []

        pairs = list(zip(strict_columns or [], unmapped_jsonb or []))
        if strict_columns and not unmapped_jsonb:
            pairs = [(s, {}) for s in strict_columns]

        review_strict: List[Dict[str, Any]] = []
        review_unmapped: List[Dict[str, Any]] = []
        for s, u in pairs:
            meta = u if isinstance(u, dict) else {}
            row_status = meta.get("row_status")
            if row_status == "FAILED_VERIFICATION" or meta.get("critic_error"):
                failed_strict.append(s)
                failed_unmapped.append(meta)
            elif status == "FAILED_VERIFICATION" and not row_status:
                failed_strict.append(s)
                failed_unmapped.append({**meta, "critic_error": meta.get("critic_error") or "document critic failed"})
            elif row_status == "NEEDS_REVIEW" or (status == "NEEDS_REVIEW" and row_status != "MAPPED"):
                review_strict.append(s)
                review_unmapped.append(meta)
            else:
                passed_strict.append(s)
                passed_unmapped.append(meta)

        if status == "FAILED_VERIFICATION" and not failed_strict and strict_columns:
            failed_strict = list(strict_columns)
            failed_unmapped = list(unmapped_jsonb or [{} for _ in strict_columns])
            passed_strict, passed_unmapped = [], []
            review_strict, review_unmapped = [], []

        async def _send(topic: str, payload: Dict[str, Any]) -> None:
            out_headers: Dict[str, Any] = {}
            inject(out_headers)
            kafka_headers = [(k, v.encode("utf-8")) for k, v in out_headers.items()]
            await self._producer.send_and_wait(
                topic,
                key=document_id.encode("utf-8"),
                value=json.dumps(payload).encode("utf-8"),
                headers=kafka_headers,
            )

        base = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "node_id": node_id,
            "user_id": original_data.get("user_id"),
            "source_page": original_data.get("source_page"),
            "source_bbox": original_data.get("source_bbox"),
            "target_table": final_table,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reflexion_meta": reflexion_meta or {},
        }
        row_id = original_data.get("row_id")
        if row_id:
            base["row_id"] = row_id

        if passed_strict:
            await _send(
                "aligned_sql_payloads",
                {
                    **base,
                    "mapping_status": "MAPPED",
                    "strict_columns": passed_strict,
                    "unmapped_jsonb": passed_unmapped,
                },
            )
            logger.info("Partial-promoted passing rows", document_id=document_id, count=len(passed_strict))

        if review_strict:
            await _send(
                "aligned_sql_payloads",
                {
                    **base,
                    "mapping_status": "NEEDS_REVIEW",
                    "strict_columns": review_strict,
                    "unmapped_jsonb": review_unmapped,
                },
            )

        if status == "FAILED_VERIFICATION" or failed_strict:
            critic_errors = []
            for meta in failed_unmapped or unmapped_jsonb or []:
                if isinstance(meta, dict) and meta.get("critic_error"):
                    critic_errors.append(str(meta["critic_error"]))
            if not critic_errors and reflexion_meta:
                critic_errors = list(reflexion_meta.get("attempt_errors") or [])

            dlq_payload = {
                **base,
                "mapping_status": "FAILED_VERIFICATION",
                "strict_columns": failed_strict or strict_columns,
                "unmapped_jsonb": failed_unmapped or unmapped_jsonb,
                "extracted_data": original_data.get("extracted_data", {}),
                "markdown_content": original_data.get("markdown_content", ""),
                "parent_section_text": original_data.get("parent_section_text", ""),
                "failure_class": (reflexion_meta or {}).get("failure_class", "retryable"),
                "reflexion_exhausted": bool((reflexion_meta or {}).get("exhausted")),
            }
            dlq_payload["hitl_review"] = await generate_hitl_review(
                target_table=final_table,
                strict_columns=dlq_payload["strict_columns"],
                unmapped_jsonb=dlq_payload["unmapped_jsonb"],
                drifted_columns=[],
                critic_errors=critic_errors,
                extracted_data=original_data.get("extracted_data", {}),
                source_headers=list((original_data.get("extracted_data") or {}).keys()),
            )
            await _send("schema_aligner_dlq", dlq_payload)
            logger.info(
                "Published payload to schema_aligner_dlq",
                document_id=document_id,
                status="FAILED_VERIFICATION",
                target_table=final_table,
                attempts=(reflexion_meta or {}).get("attempts"),
            )
        elif not passed_strict:
            await _send(
                "aligned_sql_payloads",
                {
                    **base,
                    "mapping_status": status,
                    "strict_columns": strict_columns,
                    "unmapped_jsonb": unmapped_jsonb,
                },
            )
            logger.info(
                "Published payload to aligned_sql_payloads",
                document_id=document_id,
                status=status,
                target_table=final_table,
            )

    async def _publish_anomalies(
        self,
        document_id: str,
        tenant_id: str,
        final_table: str,
        drifted_columns: List[str],
        original_data: Dict[str, Any],
        strict_columns: Optional[List[Dict[str, Any]]] = None,
        unmapped_jsonb: Optional[List[Dict[str, Any]]] = None,
        status: str = "NEEDS_REVIEW",
    ) -> None:
        if not self._producer:
            return

        hitl_review = await generate_hitl_review(
            target_table=final_table,
            strict_columns=strict_columns or [],
            unmapped_jsonb=unmapped_jsonb or [],
            drifted_columns=drifted_columns,
            critic_errors=[],
            extracted_data=original_data.get("extracted_data") or {},
            source_headers=list((original_data.get("extracted_data") or {}).keys()),
        )

        anomaly_payload = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "target_table": final_table,
            "drifted_columns": drifted_columns,
            "mapping_status": status,
            "source_page": original_data.get("source_page"),
            "source_bbox": original_data.get("source_bbox"),
            "extracted_data": original_data.get("extracted_data"),
            "strict_columns": strict_columns or [],
            "unmapped_jsonb": unmapped_jsonb or [],
            "hitl_review": hitl_review,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        out_headers: Dict[str, Any] = {}
        inject(out_headers)
        kafka_headers = [(k, v.encode("utf-8")) for k, v in out_headers.items()]

        try:
            await asyncio.wait_for(
                self._producer.send_and_wait(
                    "schema_drift_anomalies",
                    key=document_id.encode("utf-8"),
                    value=json.dumps(anomaly_payload).encode("utf-8"),
                    headers=kafka_headers
                ),
                timeout=30.0
            )
            logger.info("Published SchemaAnomaly event", document_id=document_id, count=len(drifted_columns))
        except asyncio.TimeoutError:
            logger.warning("Kafka anomaly topic creation timed out, skipping", document_id=document_id)
        except Exception as e:
            logger.error("Failed to route anomaly payload, skipping", error=str(e), document_id=document_id)
