import json
import asyncio
import structlog
import uuid
import datetime
from aiokafka import AIOKafkaConsumer
from config.settings import settings
from db.models import DeadLetterQueue
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

logger = structlog.get_logger(__name__)

class SystemDlqConsumer:
    """
    Consumes unified DLQ messages from the `system_dlq` topic and writes them
    to the `dead_letter_queues` database table, allowing them to be viewed in the UI.
    """
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory
        self._consumer = None

    async def run(self):
        self._consumer = AIOKafkaConsumer(
            "system_dlq",
            bootstrap_servers=settings.kafka_broker,
            group_id=settings.kafka_consumer_group_system_dlq,
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        
        try:
            await self._consumer.start()
            logger.info("SystemDlqConsumer started listening to system_dlq...")
            
            async for msg in self._consumer:
                await self._process_message(msg)
                
        except asyncio.CancelledError:
            logger.info("SystemDlqConsumer cancelled")
        except Exception as e:
            logger.error("SystemDlqConsumer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()

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
                payload=payload
            )
            session.add(dlq_entry)
            await session.commit()