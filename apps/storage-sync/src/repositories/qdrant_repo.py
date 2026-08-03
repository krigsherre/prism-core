import uuid
from typing import Any, Dict, List

import structlog
from qdrant_client import AsyncQdrantClient, models
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = structlog.get_logger(__name__)


class QdrantRepository:
    def __init__(self) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key if settings.qdrant_api_key != "test-qdrant-key-12345" else None, timeout=120.0)
        self.collection_name = settings.qdrant_collection_name
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def initialize_collection(self) -> None:
        try:
            await self.client.get_collection(self.collection_name)
            exists = True
        except Exception:
            exists = False
            
        if not exists:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=384,
                    distance=models.Distance.COSINE
                ),
                quantization_config=models.BinaryQuantization(
                    binary=models.BinaryQuantizationConfig(always_ram=True)
                )
            )
            logger.info(
                "Created Qdrant collection with binary quantization",
                collection=self.collection_name,
            )
            
            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="content",
                field_schema=models.TextIndexParams(
                    type="text",
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=30,
                    lowercase=True,
                )
            )
            logger.info("Created payload index for 'content' field", collection=self.collection_name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def upsert_vector(self, node_id: str, document_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node_id))
        await self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=qdrant_id,
                    vector=vector,
                    payload={
                        "document_id": document_id,
                        "original_node_id": node_id,
                        **payload
                    }
                )
            ],
            wait=False
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def upsert_batch(self, points: List[models.PointStruct]) -> None:
        if not points:
            return
        await self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=False
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def delete_vector(self, node_id: str) -> None:
        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node_id))
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(
                points=[qdrant_id],
            ),
        )
