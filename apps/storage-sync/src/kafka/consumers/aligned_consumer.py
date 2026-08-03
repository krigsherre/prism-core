import json
import datetime
from typing import Any, Dict
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from repositories.sql_repo import SQLRepository
from config.settings import settings
from kafka.consumers.base import BaseKafkaConsumer

logger = structlog.get_logger(__name__)


class AlignedSQLConsumer(BaseKafkaConsumer):
    """
    Consumes aligned SQL payloads from `aligned_sql_payloads` topic
    and persists them into PostgreSQL using SQLRepository.
    """

    def __init__(self, sql_repo: SQLRepository) -> None:
        super().__init__(
            topics=["aligned_sql_payloads"],
            group_id=settings.kafka_consumer_group_aligned,
            enable_auto_commit=False,
            needs_producer=True,
        )
        self.sql_repo = sql_repo

    def _create_consumer(self):
        return AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=settings.kafka_broker,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=self.enable_auto_commit,
        )

    def _create_producer(self):
        return AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)

    @property
    def dlq_producer(self):
        """Backwards compatibility alias for _producer."""
        return self._producer

    @dlq_producer.setter
    def dlq_producer(self, value):
        self._producer = value

    async def _process_message(self, msg) -> None:
        if not msg.value:
            return

        payload = None
        try:
            payload = json.loads(msg.value.decode("utf-8"))
            await self._process_payload_with_retry(payload)
            if self._consumer:
                await self._consumer.commit()
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON", offset=msg.offset)
            if self._consumer:
                await self._consumer.commit()
        except Exception as e:
            logger.error("Exhausted retries, routing to DLQ", error=str(e))
            await self._route_to_dlq(e, payload)
            if self._consumer:
                await self._consumer.commit()

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
                source_bbox=payload.get("source_bbox"),
            )
            logger.info(
                "Updated aligned table in SQL",
                target_table=target_table,
                mapping_status=mapping_status,
                row_id=row_id,
            )
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
                source_bbox=payload.get("source_bbox"),
            )
            logger.info("Inserted aligned rows into SQL", target_table=target_table, mapping_status=mapping_status)

        await self._emit_node_completed_status(document_id, tenant_id)

    async def _emit_node_completed_status(self, document_id: str, tenant_id: str) -> None:
        producer = self._producer or getattr(self, "dlq_producer", None)
        if not producer:
            return

        status_payload = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "sql_node_completed": True,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        try:
            await producer.send_and_wait(
                "document_status_events",
                json.dumps(status_payload).encode("utf-8"),
                key=tenant_id.encode("utf-8"),
            )
        except Exception as e:
            logger.error(f"Failed to emit status: {e}")

    async def _route_to_dlq(self, e: Exception, payload: dict) -> None:
        producer = self._producer or getattr(self, "dlq_producer", None)
        if not producer:
            return

        doc_id = payload.get("document_id", "unknown") if isinstance(payload, dict) else "unknown"
        filename = (
            payload.get("metadata", {}).get("original_filename", "unknown") if isinstance(payload, dict) else "unknown"
        )
        t_id = payload.get("tenant_id", "unknown").encode("utf-8") if isinstance(payload, dict) else b"unknown"

        fail_payload = {
            "document_id": doc_id,
            "tenant_id": t_id.decode("utf-8"),
            "filename": filename,
            "current_stage": "storage-sync",
            "status": "FAILED",
            "error_message": str(e),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        dlq_msg = {
            "tenant_id": t_id.decode("utf-8"),
            "document_id": doc_id,
            "source": "aligned-sql-consumer",
            "error": str(e),
            "payload": payload,
        }

        try:
            await producer.send_and_wait(
                "document_status_events", json.dumps(fail_payload).encode("utf-8"), key=t_id
            )
            await producer.send_and_wait("system_dlq", value=json.dumps(dlq_msg).encode("utf-8"))
        except Exception as status_e:
            logger.error(f"Failed to emit DLQ events: {status_e}")