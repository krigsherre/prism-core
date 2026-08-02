import json
import asyncio
import structlog
from aiokafka import AIOKafkaConsumer
from urllib.parse import urlparse
from config.settings import settings

logger = structlog.get_logger(__name__)

class S3CleanupConsumer:
    """
    Listens to `s3_cleanup_tasks` and deletes the orphaned S3 objects.
    """
    def __init__(self, s3_client):
        self.s3 = s3_client
        self._consumer: AIOKafkaConsumer | None = None

    async def run(self):
        self._consumer = AIOKafkaConsumer(
            "s3_cleanup_tasks",
            bootstrap_servers=settings.kafka_broker,
            group_id="s3-cleanup-consumer-group",
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        
        try:
            await self._consumer.start()
            logger.info("S3CleanupConsumer started listening to s3_cleanup_tasks...")
            
            async for msg in self._consumer:
                await self._process_message(msg)
                
        except asyncio.CancelledError:
            logger.info("S3CleanupConsumer cancelled")
        except Exception as e:
            logger.error("S3CleanupConsumer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()

    async def _process_message(self, msg):
        if not msg.value:
            return
            
        try:
            s3_uri = self._parse_payload(msg.value)
            if s3_uri:
                await self._delete_from_s3(s3_uri)
        except json.JSONDecodeError:
            logger.error("Failed to decode cleanup payload (not valid JSON)")
        except Exception as e:
            logger.error("Failed to process S3 cleanup task", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.commit()

    def _parse_payload(self, msg_value: bytes) -> str | None:
        payload = json.loads(msg_value.decode("utf-8"))
        s3_uri = payload.get("s3_uri")
        
        if not s3_uri:
            logger.warning("No s3_uri provided in cleanup task, skipping")
            return None
            
        return s3_uri

    async def _delete_from_s3(self, s3_uri: str):
        parsed = urlparse(s3_uri)
        if parsed.scheme != "s3":
            logger.warning(f"Invalid s3_uri scheme '{parsed.scheme}', expected 's3'")
            return
            
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')
        
        logger.info(f"Deleting document from S3: bucket={bucket}, key={key}")
        await asyncio.to_thread(self.s3.delete_object, Bucket=bucket, Key=key)