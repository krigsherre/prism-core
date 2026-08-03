import json
import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from config.settings import settings
from db.models import DocumentJob
from kafka.consumers.base import BaseKafkaConsumer

logger = structlog.get_logger(__name__)


class StatusConsumer(BaseKafkaConsumer):
    """
    Consumes document status updates from `document_status_events` topic
    and upserts job state in `document_jobs` table.
    """

    def __init__(self, async_session_maker) -> None:
        super().__init__(
            topics=["document_status_events"],
            group_id="storage-sync-status-group",
            enable_auto_commit=False,
        )
        self.async_session_maker = async_session_maker

    def _create_consumer(self):
        return AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=settings.kafka_broker,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=self.enable_auto_commit,
        )

    async def _process_message(self, msg) -> None:
        if not msg.value:
            return

        try:
            payload = json.loads(msg.value.decode("utf-8"))
            tenant_id = self._resolve_tenant_id(payload, msg.key)
            await self._process_status(payload, tenant_id)
            if self._consumer:
                await self._consumer.commit()
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON", offset=msg.offset)
            if self._consumer:
                await self._consumer.commit()
        except Exception as e:
            logger.error("Failed to process status event", error=str(e))
            if self._consumer:
                await self._consumer.commit()

    @staticmethod
    def _resolve_tenant_id(payload: dict, msg_key) -> str:
        """Prefer explicit payload tenant_id; never treat document_id as the tenant."""
        document_id = payload.get("document_id")
        payload_tenant = payload.get("tenant_id")
        if payload_tenant and payload_tenant != document_id:
            return payload_tenant

        if msg_key:
            key = msg_key.decode("utf-8") if isinstance(msg_key, (bytes, bytearray)) else str(msg_key)
            if key and key != document_id:
                return key

        return "default-tenant"

    async def _process_status(self, payload: dict, tenant_id: str) -> None:
        document_id = payload.get("document_id")
        if not document_id:
            logger.warning("Status event missing document_id", payload=payload)
            return

        async with self.async_session_maker() as session:
            async with session.begin():
                if payload.get("sql_node_completed") or payload.get("graph_node_completed"):
                    await self._increment_node_counters(session, payload, document_id, tenant_id)
                else:
                    await self._upsert_document_job(session, payload, document_id, tenant_id)

    async def _increment_node_counters(self, session, payload: dict, document_id: str, tenant_id: str) -> None:
        update_stmt = update(DocumentJob).where(
            DocumentJob.document_id == document_id,
            DocumentJob.tenant_id == tenant_id,
        )

        if payload.get("sql_node_completed"):
            update_stmt = update_stmt.values(sql_nodes_completed=DocumentJob.sql_nodes_completed + 1)
        if payload.get("graph_node_completed"):
            update_stmt = update_stmt.values(graph_nodes_completed=DocumentJob.graph_nodes_completed + 1)

        update_stmt = update_stmt.returning(
            DocumentJob.sql_nodes_total,
            DocumentJob.sql_nodes_completed,
            DocumentJob.graph_nodes_total,
            DocumentJob.graph_nodes_completed,
        )

        result = await session.execute(update_stmt)
        row = result.fetchone()

        if not row:
            await self._upsert_document_job(
                session,
                {
                    **payload,
                    "filename": payload.get("filename") or "unknown",
                    "status": payload.get("status") or "IN_PROGRESS",
                    "current_stage": payload.get("current_stage") or "ingesting",
                },
                document_id,
                tenant_id,
            )
            return

        if row:
            sql_t, sql_c, grp_t, grp_c = row
            is_complete = (sql_c >= sql_t and grp_c >= grp_t) and (sql_t > 0 or grp_t > 0)

            if is_complete:
                new_status = "COMPLETED"
                new_stage = "Completed"
            else:
                new_status = "IN_PROGRESS"
                new_stage = f"Ingesting (SQL: {sql_c}/{sql_t}, Graph: {grp_c}/{grp_t})"

            await session.execute(
                update(DocumentJob)
                .where(DocumentJob.document_id == document_id)
                .values(status=new_status, current_stage=new_stage)
            )
            logger.info(
                "Incremented node counters",
                document_id=document_id,
                sql_completed=sql_c,
                sql_total=sql_t,
                graph_completed=grp_c,
                graph_total=grp_t,
                status=new_status,
            )

    async def _upsert_document_job(self, session, payload: dict, document_id: str, tenant_id: str) -> None:
        status = payload.get("status", "UNKNOWN")
        sql_nodes_total = payload.get("sql_nodes_total")
        graph_nodes_total = payload.get("graph_nodes_total")

        current_stage = payload.get("current_stage", "unknown")
        if status == "IN_PROGRESS" and (sql_nodes_total or graph_nodes_total):
            current_stage = f"Ingesting (SQL: 0/{sql_nodes_total or 0}, Graph: 0/{graph_nodes_total or 0})"

        insert_values = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": payload.get("filename") or "unknown",
            "current_stage": current_stage,
            "status": status,
            "error_message": payload.get("error_message"),
        }

        optional_fields = [
            "s3_uri",
            "file_hash",
            "sql_mapped",
            "vector_mapped",
            "graph_mapped",
            "sql_nodes_total",
            "graph_nodes_total",
            "company_name",
            "ticker",
            "fiscal_period",
        ]
        for field in optional_fields:
            if payload.get(field) is not None:
                insert_values[field] = payload.get(field)

        stmt = insert(DocumentJob).values(**insert_values)

        incoming_filename = insert_values.get("filename") or "unknown"
        update_set = {
            k: getattr(stmt.excluded, k)
            for k in insert_values.keys()
            if k not in ("document_id", "filename", "s3_uri", "file_hash")
        }
        if incoming_filename and incoming_filename != "unknown":
            update_set["filename"] = stmt.excluded.filename
        else:
            update_set["filename"] = DocumentJob.filename

        if insert_values.get("s3_uri"):
            update_set["s3_uri"] = stmt.excluded.s3_uri
        if insert_values.get("file_hash"):
            update_set["file_hash"] = stmt.excluded.file_hash

        do_update_stmt = stmt.on_conflict_do_update(index_elements=["document_id"], set_=update_set)

        await session.execute(do_update_stmt)
        logger.info("UPSERT DocumentJob status", document_id=document_id, tenant_id=tenant_id, status=status)