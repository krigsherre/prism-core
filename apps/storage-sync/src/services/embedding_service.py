import asyncio
from typing import Dict, List, Optional
import httpx
import structlog
from proto.prism.v1 import dom_pb2

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """
    Service for generating vector embeddings via TEI (Text Embeddings Inference) server.
    Handles single text embeddings and high-throughput batch precomputation.
    """

    def __init__(
        self,
        embeddings_url: str = "http://embeddings-server:8080/v1/embeddings",
        batch_url: str = "http://embeddings-server:80/embed",
        vector_dim: int = 384,
        max_concurrent: int = 10,
    ) -> None:
        self.embeddings_url = embeddings_url
        self.batch_url = batch_url
        self.vector_dim = vector_dim
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def fallback_vector(self) -> List[float]:
        """Generate a zero-filled vector fallback."""
        return [0.0] * self.vector_dim

    def default_node_vector(self) -> List[float]:
        """Generate default small non-zero vector for un-embedded nodes."""
        return [1e-5] * self.vector_dim

    async def get_single_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text snippet using standard TEI OpenAI endpoint."""
        safe_text = text[:2000] if text else ""
        if not safe_text:
            return self.fallback_vector()

        try:
            async with self._semaphore:
                response = await self._http_client.post(
                    self.embeddings_url,
                    json={"input": safe_text, "model": "sentence-transformers/all-MiniLM-L6-v2"},
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()["data"][0]["embedding"]
        except Exception as e:
            logger.error("Failed to generate embedding from TEI", error=str(e))
            return self.fallback_vector()

    async def precompute_embeddings(self, nodes: List[dom_pb2.Node]) -> Dict[str, List[float]]:
        """Precompute TEI embeddings in batches for a tree of DocumentDOM nodes."""
        texts_to_embed: List[tuple[str, str]] = []

        def _collect(n_list: List[dom_pb2.Node]):
            for n in n_list:
                if n.content and n.content.strip() and n.type != dom_pb2.NODE_TYPE_IMAGE:
                    texts_to_embed.append((n.id, n.content[:2000]))
                if len(n.children) > 0:
                    _collect(list(n.children))

        _collect(nodes)

        if not texts_to_embed:
            return {}

        embeddings_map: Dict[str, List[float]] = {}
        batch_size = 8

        for i in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[i : i + batch_size]
            batch_ids = [item[0] for item in batch]
            batch_texts = [item[1] for item in batch]

            try:
                response = await self._http_client.post(
                    self.batch_url,
                    json={"inputs": batch_texts},
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        for idx, b_id in enumerate(batch_ids):
                            if idx < len(data):
                                embeddings_map[b_id] = data[idx]
                else:
                    logger.error("TEI batch embedding returned non-200", status=response.status_code)
            except Exception as e:
                logger.error("TEI batch embedding failed", error=repr(e))

        return embeddings_map

    def get_embedding_for_node(self, node: dom_pb2.Node, precomputed: Dict[str, List[float]]) -> List[float]:
        """Look up precomputed vector for node, defaulting to default_node_vector()."""
        if precomputed and node.id in precomputed:
            return precomputed[node.id]
        return self.default_node_vector()

    async def close(self) -> None:
        """Close HTTP client connection."""
        await self._http_client.aclose()
