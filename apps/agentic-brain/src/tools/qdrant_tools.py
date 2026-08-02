import json
import httpx
import structlog
from langchain_core.tools import tool
from qdrant_client import AsyncQdrantClient, models
from core.config import settings

logger = structlog.get_logger(__name__)

@tool
async def query_vector_db(query: str, tenant_id: str, document_id: str = None) -> str:
    """
    Queries the Qdrant Vector database for semantic similarity.
    Use this for unstructured questions like "Find clauses about late fees".
    Returns the most relevant text chunks and their bounding boxes (for provenance).
    """
    logger.info("Querying Vector DB", query=query, tenant_id=tenant_id, document_id=document_id)
    
    try:
        embed_endpoint = settings.embeddings_api_url.rstrip("/")
        if not embed_endpoint.endswith("/embed"):
            embed_endpoint = f"{embed_endpoint}/embed"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                embed_endpoint,
                json={"inputs": query[:2000]}
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                vector = data[0] if isinstance(data[0], list) else data
            else:
                raise ValueError("Invalid embedding response")

        collection = settings.qdrant_collection or "document_chunks"
        qdrant_client = AsyncQdrantClient(url=settings.qdrant_url)
        
        must_conditions = [models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
        if document_id:
            must_conditions.append(models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)))

        # qdrant-client >=1.12: AsyncQdrantClient.search was removed; use query_points
        search_result = await qdrant_client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=models.Filter(must=must_conditions),
            limit=5,
            with_payload=True,
        )
        
        results = []
        points = getattr(search_result, "points", None) or search_result or []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            results.append({
                "text": payload.get("content", payload.get("text", "")),
                "source_page": payload.get("source_page", 1),
                "source_bbox": payload.get("source_bbox", [0,0,0,0]),
                "document_id": payload.get("document_id", document_id),
                "score": getattr(point, "score", None),
            })
            
        return json.dumps(results, indent=2)
    except Exception as e:
        logger.error("Vector query failed", error=str(e))
        return json.dumps({"error": f"Failed to query Vector DB: {e}", "results": []})
