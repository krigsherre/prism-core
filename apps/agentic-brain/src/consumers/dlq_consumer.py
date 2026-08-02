import asyncio
import json
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, Any, Dict, List
import uuid
from core.db import db_client
from core.config import settings
from utils.hitl_review import generate_hitl_review_from_dlq

logger = structlog.get_logger(__name__)

_PERMANENT_HINTS = (
    "permanent",
    "no critic registered",
    "unknown_table",
    "could not classify",
    "empty extracted",
    "file not found",
    "ocr returned empty",
    "missing page",
    "unsupported schema",
)


def _extract_critic_error(payload: Dict[str, Any]) -> str:
    unmapped = payload.get("unmapped_jsonb", {})
    if isinstance(unmapped, list) and unmapped:
        return str(unmapped[0].get("critic_error", "") or "")
    if isinstance(unmapped, dict):
        return str(unmapped.get("critic_error", "") or "")
    return ""


def _is_permanent_failure(payload: Dict[str, Any], critic_error: str) -> bool:
    if payload.get("failure_class") == "permanent":
        return True
    if payload.get("reflexion_exhausted"):
        return True
    meta = payload.get("reflexion_meta") or {}
    if isinstance(meta, dict) and meta.get("failure_class") == "permanent":
        return True
    if isinstance(meta, dict) and meta.get("exhausted"):
        return True
    blob = f"{critic_error} {payload.get('mapping_status', '')}".lower()
    return any(h in blob for h in _PERMANENT_HINTS)


class DLQConsumer:
    def __init__(self) -> None:
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._redis: Optional[redis.Redis] = None

    @retry(stop=stop_after_attempt(settings.kafka_max_retries), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect(self) -> None:
        if self._consumer:
            await self._consumer.start()
        if self._producer:
            await self._producer.start()
        self._redis = redis.from_url(settings.redis_url)
        await self._redis.ping()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "schema_aligner_dlq",
            bootstrap_servers=settings.kafka_broker,
            group_id="agentic-brain-dlq",
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect()
            logger.info("DLQConsumer connected to Kafka and Redis.")
        except Exception as e:
            logger.error("Failed to connect DLQConsumer", error=str(e))
            return

        logger.info("DLQConsumer started listening to schema_aligner_dlq")

        try:
            if self._consumer is None:
                return
            async for msg in self._consumer:
                if not msg.value:
                    continue
                try:
                    payload: Dict[str, Any] = json.loads(msg.value.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.warning("Failed to decode DLQ payload")
                    continue

                try:
                    await self._handle_payload(payload)
                except Exception as e:
                    logger.error("DLQ handler failed", error=str(e), document_id=payload.get("document_id"))
                finally:
                    await self._consumer.commit()
                
        except asyncio.CancelledError:
            logger.info("DLQConsumer cancelled")
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self._producer:
                await self._producer.stop()
            if self._redis:
                await self._redis.aclose()

    async def _handle_payload(self, payload: Dict[str, Any]) -> None:
        document_id: str = payload.get("document_id", "unknown")
        tenant_id: str = payload.get("tenant_id", "unknown")
        critic_error = _extract_critic_error(payload)

        if not critic_error and payload.get("mapping_status") not in ("FAILED_VERIFICATION", "FAILED"):
            logger.info("Payload in DLQ is not a verification failure, ignoring", document_id=document_id)
            return

        if self._redis is None or self._producer is None:
            return

        if _is_permanent_failure(payload, critic_error):
            logger.warning(
                "Permanent or exhausted failure — escalating to HITL",
                document_id=document_id,
                critic_error=critic_error,
            )
            await self._escalate_to_hitl(payload, critic_error)
            return

        retry_key: str = f"dlq:retry_count:{document_id}"
        current_retries_bytes: Optional[bytes] = await self._redis.get(retry_key)
        current_retries: int = int(current_retries_bytes) if current_retries_bytes else 0

        if current_retries < settings.max_retries:
            logger.info(
                "Reflexion Kafka retry → raw_table_doms",
                document_id=document_id,
                retry_count=current_retries + 1,
                max_retries=settings.max_retries,
            )
            await self._redis.incr(retry_key)
            await self._redis.expire(retry_key, settings.retry_expiry_seconds)

            task_id = str(uuid.uuid4())
            if not db_client.pool:
                await db_client.connect()
            async with db_client.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO dead_letter_queues (task_id, tenant_id, document_id, agent_name, error, payload) VALUES ($1, $2, $3, $4, $5, $6)",
                    task_id, tenant_id, document_id, "schema_aligner_dlq", critic_error or "verification failed", json.dumps(payload)
                )

            extracted_data: Dict[str, Any] = payload.get("extracted_data") or {}
            previous: Any = payload.get("strict_columns") or extracted_data
            retry_payload: Dict[str, Any] = {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "node_id": payload.get("node_id"),
                "user_id": payload.get("user_id", ""),
                "source_page": payload.get("source_page", 1),
                "source_bbox": payload.get("source_bbox"),
                "target_table": payload.get("target_table"),
                "target_schema": payload.get("target_table"),
                "extracted_data": extracted_data,
                "markdown_content": payload.get("markdown_content", ""),
                "parent_section_text": payload.get("parent_section_text", ""),
                "reflexion_error": critic_error,
                "previous_extraction": previous,
                "reflexion_attempt": current_retries + 1,
                "row_id": payload.get("row_id"),
            }

            await self._producer.send_and_wait(
                "raw_table_doms",
                key=document_id.encode("utf-8"),
                value=json.dumps(retry_payload).encode("utf-8")
            )
        else:
            logger.warning("Max Kafka retries exceeded, sending to HITL review", document_id=document_id)
            await self._escalate_to_hitl(payload, critic_error)

    async def _escalate_to_hitl(self, payload: Dict[str, Any], critic_error: str) -> None:
        if self._producer is None or self._redis is None:
            return

        document_id: str = payload.get("document_id", "unknown")
        tenant_id: str = payload.get("tenant_id", "unknown")

        hitl_review = await generate_hitl_review_from_dlq(payload, critic_error)
        enriched_payload = dict(payload)
        enriched_payload["hitl_review"] = hitl_review
        if payload.get("reflexion_meta"):
            enriched_payload["reflexion_meta"] = payload["reflexion_meta"]

        hitl_payload: Dict[str, Any] = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "error": hitl_review.get("summary") or critic_error,
            "payload": enriched_payload,
            "hitl_review": hitl_review,
        }
        await self._producer.send_and_wait(
            "hitl_review",
            key=document_id.encode("utf-8"),
            value=json.dumps(hitl_payload).encode("utf-8")
        )

        hitl_id = str(uuid.uuid4())
        if not db_client.pool:
            await db_client.connect()
        async with db_client.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO hitl_requests (id, tenant_id, document_id, status, error, payload) VALUES ($1, $2, $3, 'PENDING', $4, $5)",
                hitl_id, tenant_id, document_id, hitl_review.get("summary") or critic_error, json.dumps(enriched_payload)
            )

        await self._redis.hset(f"hitl:payload:{document_id}", mapping={"data": json.dumps(enriched_payload)})
        await self._redis.expire(f"hitl:payload:{document_id}", settings.hitl_timeout_seconds)

        timeout_key: str = f"hitl:timeout:{document_id}"
        await self._redis.set(timeout_key, "waiting", ex=settings.hitl_timeout_seconds)
