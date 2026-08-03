import json
import uuid
import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy.orm import sessionmaker
from config.settings import settings
from db.models import HitlRequest
from kafka.consumers.base import BaseKafkaConsumer

logger = structlog.get_logger(__name__)


class HitlConsumer(BaseKafkaConsumer):
    """
    Consumes messages from the `schema_drift_anomalies` topic and writes them
    to the `hitl_requests` database table for human review.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        super().__init__(
            topics=["schema_drift_anomalies"],
            group_id="hitl-consumer-group",
            enable_auto_commit=False,
        )
        self.session_factory = session_factory

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
            await self._insert_hitl_entry(payload)
        except json.JSONDecodeError:
            logger.error("Failed to decode HITL payload (not valid JSON)")
        except Exception as e:
            logger.error("Failed to process HITL message", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.commit()

    def _build_error_message(self, payload: dict) -> str:
        hitl_review = payload.get("hitl_review") or {}
        if isinstance(hitl_review, dict) and hitl_review.get("summary"):
            issues = hitl_review.get("issues") or []
            questions = [iss.get("question") for iss in issues[:3] if isinstance(iss, dict) and iss.get("question")]
            if questions:
                return hitl_review["summary"] + " | " + " · ".join(questions)
            return hitl_review["summary"]

        target_table = payload.get("target_table", "unknown")
        drifted_columns = payload.get("drifted_columns", [])
        if drifted_columns:
            return f"Schema anomaly on {target_table}: drifted columns detected ({', '.join(drifted_columns)})"
        return f"Schema anomaly on {target_table}: high unmapped ratio or missing expected columns"

    async def _insert_hitl_entry(self, payload: dict) -> None:
        tenant_id = payload.get("tenant_id", "unknown")
        document_id = payload.get("document_id", "unknown")
        error_msg = self._build_error_message(payload)

        async with self.session_factory() as session:
            hitl_entry = HitlRequest(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                document_id=document_id,
                status="PENDING",
                error=error_msg,
                payload=payload,
            )
            session.add(hitl_entry)
            await session.commit()
