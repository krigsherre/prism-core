import asyncio
import json
import structlog
import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, Any, Dict

from core.config import settings

logger = structlog.get_logger(__name__)

class RedisKeyspaceListener:
    def __init__(self) -> None:
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._producer: Optional[AIOKafkaProducer] = None

    @retry(stop=stop_after_attempt(settings.redis_max_retries), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect(self) -> None:
        self._redis = redis.from_url(settings.redis_url)
        await self._redis.ping()
        
        await self._redis.config_set("notify-keyspace-events", "Ex")
        
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe("__keyevent@0__:expired")
        
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        await self._producer.start()

    async def run(self) -> None:
        try:
            await self._connect()
            logger.info("RedisKeyspaceListener connected to Redis and Kafka.")
        except Exception as e:
            logger.error("Failed to connect RedisKeyspaceListener", error=str(e))
            return

        logger.info("Listening for Redis expiry events...")
        
        try:
            while True:
                if self._pubsub:
                    message: Optional[Dict[str, Any]] = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and isinstance(message.get("data"), bytes):
                        expired_key: str = message["data"].decode("utf-8")
                        if expired_key.startswith("hitl:timeout:"):
                            document_id: str = expired_key.split("hitl:timeout:")[1]
                            logger.warning("HITL Timeout expired for document", document_id=document_id)
                            await self._handle_timeout(document_id)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("RedisKeyspaceListener cancelled")
        finally:
            if self._pubsub:
                await self._pubsub.unsubscribe()
            if self._redis:
                await self._redis.aclose()
            if self._producer:
                await self._producer.stop()

    async def _handle_timeout(self, document_id: str) -> None:
        try:
            if not self._redis or not self._producer:
                return
                
            payload_key: str = f"hitl:payload:{document_id}"
            payload_data: Optional[bytes] = await self._redis.hget(payload_key, "data")
            
            if payload_data:
                await self._producer.send_and_wait(
                    "permanent_failure",
                    key=document_id.encode("utf-8"),
                    value=payload_data
                )
                logger.info("Routed timed-out document to permanent_failure topic", document_id=document_id)
                
                await self._redis.delete(payload_key)
            else:
                logger.warning("No payload found for expired document", document_id=document_id)
        except Exception as e:
            logger.error("Failed to handle HITL timeout", error=str(e), document_id=document_id)
