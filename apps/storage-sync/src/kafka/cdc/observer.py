import json
import structlog
from aiokafka import AIOKafkaConsumer
from repositories.qdrant_repo import QdrantRepository
from services.embedding_service import EmbeddingService
from core.parsers.table_parser import TableParser
from kafka.consumers.base import BaseKafkaConsumer

logger = structlog.get_logger(__name__)


class DebeziumObserver(BaseKafkaConsumer):
    """
    Observer listening to Debezium Postgres CDC stream on `postgres.public.extracted_tables.events`
    and updating Qdrant vector index in real-time on table row inserts, updates, or deletes.
    """

    def __init__(
        self,
        qdrant_repo: QdrantRepository,
        embeddings_url: str = "http://embeddings-server:8080/v1/embeddings",
    ) -> None:
        super().__init__(
            topics=["postgres.public.extracted_tables.events"],
            group_id="storage-sync-cdc",
            auto_offset_reset="earliest",
        )
        self.qdrant_repo = qdrant_repo
        self.embedding_service = EmbeddingService(embeddings_url=embeddings_url)

    def _create_consumer(self):
        return AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self.topics[0],  # settings reference
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
        )

    async def _real_embedding(self, text: str):
        """Embedding generation method preserved for backwards compatibility and testing."""
        return await self.embedding_service.get_single_embedding(text)

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
            for separator in ["\n\n", "\n", ". ", " "]:
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
                        "original_node_id": node_id,
                    },
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