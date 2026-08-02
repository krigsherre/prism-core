import asyncio
import os
import json
import httpx
import structlog
from aiokafka import AIOKafkaConsumer
from repositories.qdrant_repo import QdrantRepository
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

class DebeziumObserver:
    def __init__(self, qdrant_repo: QdrantRepository, embeddings_url="http://embeddings-server:8080/v1/embeddings") -> None:
        self.qdrant_repo = qdrant_repo
        self._consumer = None
        self.embeddings_url = embeddings_url

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()
            
    async def _real_embedding(self, text: str):
        safe_text = text[:2000] if text else ""
        if not safe_text:
            return [0.0] * 384
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.embeddings_url,
                    json={"input": safe_text, "model": "sentence-transformers/all-MiniLM-L6-v2"},
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()["data"][0]["embedding"]
        except Exception as e:
            logger.error("Failed to generate embedding from TEI", error=str(e))
            return [0.0] * 384
            
    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "postgres.public.extracted_tables.events",
            bootstrap_servers=settings.kafka_broker,
            group_id="storage-sync-cdc",
            auto_offset_reset="earliest"
        )
        
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect CDC Observer to Kafka", error=str(e))
            return
            
        logger.info("Debezium CDC Observer started...")
        
        try:
            async for msg in self._consumer:
                await self._process_message(msg)
        except asyncio.CancelledError:
            logger.info("CDC Observer cancelled")
        except Exception as e:
            logger.error("CDC Observer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()

    async def _process_message(self, msg) -> None:
        if not msg.value:
            return
            
        try:
            payload = json.loads(msg.value.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("Failed to decode CDC JSON payload")
            return
            
        op = payload.get("payload", {}).get("op", "")
        
        if op in ("u", "c"):
            await self._handle_upsert(payload, op)
        elif op == "d":
            await self._handle_delete(payload)

    def _chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
        if not text:
            return [""]
        chunks = []
        i = 0
        while i < len(text):
            end = min(i + chunk_size, len(text))
            if end == len(text):
                chunks.append(text[i:end].strip())
                break
                
            best_break = end
            for separator in ['\n\n', '\n', '. ', ' ']:
                pos = text.rfind(separator, i, end)
                if pos != -1 and pos > i + overlap:
                    best_break = pos + len(separator)
                    break
                    
            chunks.append(text[i:best_break].strip())
            advancement = max(1, best_break - i - overlap)
            i += advancement
            
        return [c for c in chunks if c] or [""]

    async def _handle_upsert(self, payload: dict, op: str) -> None:
        after_state = payload.get("payload", {}).get("after", {})
        node_id = after_state.get("node_id")
        document_id = after_state.get("document_id")
        content = after_state.get("content", "")
        source_page = after_state.get("source_page", 1)
        source_bbox = after_state.get("source_bbox", [0, 0, 0, 0])
        
        if not (node_id and document_id):
            return
            
        try:
            chunks = self._chunk_text(content)
            for i, chunk in enumerate(chunks):
                vector = await self._real_embedding(chunk)
                chunk_node_id = f"{node_id}_{i}" if len(chunks) > 1 else node_id
                
                await self.qdrant_repo.upsert_vector(
                    node_id=chunk_node_id,
                    document_id=document_id,
                    vector=vector,
                    payload={
                        "tenant_id": after_state.get("tenant_id"),
                        "text": chunk,
                        "source_page": source_page,
                        "source_bbox": source_bbox,
                        "cdc_synced": True,
                        "original_node_id": node_id
                    }
                )
            logger.info("Synced updated Postgres row to Qdrant", node_id=node_id, op=op, chunks=len(chunks))
        except Exception as e:
            logger.error("Failed to sync updated Postgres row to Qdrant", error=str(e), node_id=node_id)

    async def _handle_delete(self, payload: dict) -> None:
        before_state = payload.get("payload", {}).get("before", {})
        node_id = before_state.get("node_id")
        
        if not node_id:
            return
            
        try:
            await self.qdrant_repo.delete_vector(node_id)
            logger.info("Deleted Postgres row from Qdrant", node_id=node_id)
        except Exception as e:
            logger.error("Failed to delete vector from Qdrant", error=str(e), node_id=node_id)