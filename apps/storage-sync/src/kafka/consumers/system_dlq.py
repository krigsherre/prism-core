import json
import uuid
import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy.orm import sessionmaker
from config.settings import settings
from db.models import DeadLetterQueue
from kafka.consumers.base import BaseKafkaConsumer

logger = structlog.get_logger(__name__)


class SystemDlqConsumer(BaseKafkaConsumer):
    """
    Consumes unified DLQ messages from the `system_dlq` topic and writes them
    to the `dead_letter_queues` database table, allowing them to be viewed in the UI.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        super().__init__(
            topics=["system_dlq"],
            group_id=settings.kafka_consumer_group_system_dlq,
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
            await self._insert_dlq_entry(payload)
        except json.JSONDecodeError:
            logger.error("Failed to decode DLQ payload (not valid JSON)")
        except Exception as e:
            logger.error("Failed to process system DLQ message", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.commit()

    async def _insert_dlq_entry(self, payload: dict) -> None:
        tenant_id = payload.get("tenant_id", "unknown")
        document_id = payload.get("document_id", payload.get("event_id", "unknown"))
        error_msg = payload.get("error", "Unknown error")
        agent_name = payload.get("source", "system")

        async with self.session_factory() as session:
            dlq_entry = DeadLetterQueue(
                task_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                document_id=document_id,
                agent_name=agent_name,
                error=error_msg,
                payload=payload,
            )
            session.add(dlq_entry)
            await session.commit()