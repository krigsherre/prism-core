import asyncio
import os
import json
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from repositories.sql_repo import SQLRepository
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

class AutoPromoteConsumer:
    """
    Listens for schema_cdc and dictionary_cdc events.
    When a schema changes, we fetch any 'NEEDS_REVIEW' rows for that table
    (and UNKNOWN_TABLE) and re-route them into 'raw_table_doms' for re-alignment.
    """
    def __init__(self, sql_repo: SQLRepository) -> None:
        self.sql_repo = sql_repo
        self._consumer = None
        self._producer = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()
        if self._producer:
            await self._producer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "schema_cdc", "dictionary_cdc",
            bootstrap_servers=settings.kafka_broker,
            group_id=settings.kafka_consumer_group_auto_promote,
            auto_offset_reset="earliest"
        )
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect AutoPromoteConsumer to Kafka", error=str(e))
            return
            
        logger.info("AutoPromoteConsumer started listening for schema changes...")
        
        try:
            async for msg in self._consumer:
                await self._process_message(msg)
        except asyncio.CancelledError:
            logger.info("AutoPromoteConsumer cancelled")
        except Exception as e:
            logger.error("AutoPromoteConsumer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self._producer:
                await self._producer.stop()

    async def _process_message(self, msg) -> None:
        if not msg.value:
            return
            
        try:
            payload = json.loads(msg.value.decode("utf-8"))
        except json.JSONDecodeError:
            return
            
        op = payload.get("payload", {}).get("op", "")
        if op in ("c", "u"):
            target_table = payload.get("payload", {}).get("after", {}).get("target_table")
            if target_table:
                await self._handle_schema_update(target_table)

    async def _handle_schema_update(self, target_table: str) -> None:
        rows = await self.sql_repo.get_unmapped_rows_by_table(target_table)
        if not rows:
            return
            
        logger.info("Auto-Promoting stuck rows for new schema", target_table=target_table, count=len(rows))
        
        for row in rows:
            await self._requeue_row_for_alignment(row, target_table)

    async def _requeue_row_for_alignment(self, row: dict, target_table: str) -> None:
        extracted_data = {**row.get("strict_columns", {}), **row.get("unmapped_jsonb", {})}
        
        payload = {
            "row_id": row["id"],
            "document_id": row["document_id"],
            "tenant_id": row["tenant_id"],
            "target_table": target_table,
            "extracted_data": extracted_data
        }
        
        await self._producer.send_and_wait(
            "raw_table_doms",
            key=row["document_id"].encode("utf-8"),
            value=json.dumps(payload).encode("utf-8")
        )
        logger.info("Re-queued row for Auto-Promotion", row_id=row["id"], document_id=row["document_id"])