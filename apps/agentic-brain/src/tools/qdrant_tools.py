"""Vector search engine for Qdrant similarity and semantic reranking."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import httpx
import structlog
from langchain_core.tools import tool
from qdrant_client import AsyncQdrantClient, models

from core.config import settings

logger = structlog.get_logger(__name__)


class VectorSearchEngine:
    """Engine for performing embedding search and neural reranking over Qdrant collections."""

    def __init__(
        self,
        embeddings_url: str = settings.embeddings_api_url,
        reranker_url: str = settings.reranker_api_url,
        qdrant_url: str = settings.qdrant_url,
        collection_name: str = settings.qdrant_collection or "document_chunks",
    ) -> None:
        self.embeddings_url = embeddings_url
        self.reranker_url = reranker_url
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name

    async def _generate_embeddings(self, query: str) -> List[float]:
        embed_endpoint = self.embeddings_url.rstrip("/")
        if not embed_endpoint.endswith("/embed"):
            embed_endpoint = f"{embed_endpoint}/embed"

        async with httpx.AsyncClient(timeout=10.0) as client:
            bge_query = f"Represent this sentence for searching relevant passages: {query[:1900]}"
            response = await client.post(embed_endpoint, json={"inputs": bge_query})
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0] if isinstance(data[0], list) else data
            raise ValueError("Invalid embedding response")

    def _keyword_score(self, query: str, point: Any) -> float:
        """Calculate fallback relevance score based on keyword overlap with financial query."""
        payload = getattr(point, "payload", None) or {}
        text = str(payload.get("text", payload.get("content", payload.get("parent_section_text", "")))).lower()
        query_words = [w for w in query.lower().split() if len(w) > 2]
        score = 0.0
        for w in query_words:
            if w in text:
                score += 1.0
        # Give high weight to critical financial line items
        financial_terms = ["operating income", "interest expense", "term loan", "ebit", "cash and cash equivalents", "short-term debt", "repayable", "repay"]
        for ft in financial_terms:
            if ft in text:
                score += 3.0
        return score

    async def _rerank(
        self, query: str, points: List[Any], top_k: int = 5
    ) -> List[Any]:
        if not points:
            return []
        
        # Take top candidate points to prevent payload explosion
        candidates = points[:15]
        try:
            texts_to_rerank = []
            for point in candidates:
                payload = getattr(point, "payload", None) or {}
                # Prefer exact node text snippet over long parent_section_text
                text_content = payload.get("text", payload.get("content", payload.get("parent_section_text", "")))
                texts_to_rerank.append(str(text_content)[:500])

            rerank_endpoint = self.reranker_url.rstrip("/")
            if not rerank_endpoint.endswith("/rerank"):
                rerank_endpoint = f"{rerank_endpoint}/rerank"

            async with httpx.AsyncClient(timeout=3.0) as client:
                rerank_resp = await client.post(
                    rerank_endpoint,
                    json={"query": query, "texts": texts_to_rerank},
                )
                if rerank_resp.status_code == 200:
                    rerank_data = rerank_resp.json()
                    top_indices = [item["index"] for item in rerank_data[:top_k] if item.get("index") < len(candidates)]
                    if top_indices:
                        return [candidates[idx] for idx in top_indices]
                
                logger.warning(
                    "Reranker returned non-200, falling back to keyword relevance ordering",
                    status=rerank_resp.status_code,
                )
        except Exception as e:
            logger.warning("Neural reranking failed/timed out, using keyword relevance ordering", error=str(e))

        # Fallback: Sort candidates by keyword overlap score
        sorted_candidates = sorted(candidates, key=lambda p: self._keyword_score(query, p), reverse=True)
        return sorted_candidates[:top_k]

    async def query(
        self, query: str, tenant_id: str, document_id: Optional[str] = None
    ) -> str:
        """Execute vector search query and rerank top results."""
        logger.info("Querying Vector DB", query=query, tenant_id=tenant_id, document_id=document_id)
        try:
            vector = await self._generate_embeddings(query)
            qdrant_client = AsyncQdrantClient(url=self.qdrant_url)

            must_conditions = [
                models.FieldCondition(
                    key="tenant_id", match=models.MatchValue(value=tenant_id)
                )
            ]
            if document_id:
                must_conditions.append(
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )
                )

            search_result = await qdrant_client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=models.Filter(must=must_conditions),
                limit=50,
                with_payload=True,
            )

            points = getattr(search_result, "points", None) or search_result or []
            
            # Fallback: If strict document_id filter yielded no points, retry with tenant_id filter only
            if not points and document_id:
                logger.info("Strict document_id vector search yielded no points; falling back to tenant_id search", document_id=document_id)
                fallback_conditions = [
                    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))
                ]
                search_result = await qdrant_client.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    query_filter=models.Filter(must=fallback_conditions),
                    limit=50,
                    with_payload=True,
                )
                points = getattr(search_result, "points", None) or search_result or []

            if not points:
                return "No relevant documents found."

            best_points = await self._rerank(query, points, top_k=5)

            results = []
            for point in best_points:
                payload = getattr(point, "payload", None) or {}
                results.append({
                    "text": payload.get(
                        "parent_section_text", payload.get("content", payload.get("text", ""))
                    ),
                    "source_page": payload.get("source_page", 1),
                    "source_bbox": payload.get("source_bbox", []),
                    "document_id": payload.get("document_id", ""),
                    "score": getattr(point, "score", None),
                })

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error("Vector query failed", error=str(e))
            return json.dumps({"error": f"Failed to query Vector DB: {e}", "results": []})


vector_engine = VectorSearchEngine()


@tool
async def query_vector_db(query: str, tenant_id: str, document_id: str = None) -> str:
    """
    Queries the Qdrant Vector database for semantic similarity.
    Use this for unstructured questions like "Find clauses about late fees".
    Returns the most relevant text chunks and their bounding boxes (for provenance).
    """
    return await vector_engine.query(query, tenant_id, document_id)
