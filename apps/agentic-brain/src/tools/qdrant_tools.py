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
            # BGE models require a specific instruction prefix for search queries
            bge_query = f"Represent this sentence for searching relevant passages: {query[:1900]}"
            response = await client.post(
                embed_endpoint,
                json={"inputs": bge_query}
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
            limit=50,
            with_payload=True,
        )
        
        points = getattr(search_result, "points", None) or search_result or []
        if not points:
            return "No relevant documents found."
            
        # Reranking using TEI bge-reranker-base
        try:
            texts_to_rerank = []
            for point in points:
                payload = getattr(point, "payload", None) or {}
                # Use parent_section_text for broader context if available
                text_content = payload.get("parent_section_text", payload.get("content", payload.get("text", "")))
                texts_to_rerank.append(text_content)
                
            rerank_endpoint = settings.reranker_api_url.rstrip("/")
            if not rerank_endpoint.endswith("/rerank"):
                rerank_endpoint = f"{rerank_endpoint}/rerank"
                
            async with httpx.AsyncClient(timeout=10.0) as client:
                rerank_resp = await client.post(
                    rerank_endpoint,
                    json={
                        "query": query,
                        "texts": texts_to_rerank
                    }
                )
                if rerank_resp.status_code == 200:
                    rerank_data = rerank_resp.json()
                    # TEI returns a list of dicts with 'index' and 'score'
                    # e.g., [{"index": 5, "score": 0.99}, ...]
                    top_indices = [item["index"] for item in rerank_data[:5]]
                    best_points = [points[idx] for idx in top_indices]
                else:
                    logger.warning("Reranker failed, falling back to original ordering", status=rerank_resp.status_code)
                    best_points = points[:5]
        except Exception as e:
            logger.error("Reranking failed", error=str(e))
            best_points = points[:5]
        
        results = []
        for point in best_points:
            payload = getattr(point, "payload", None) or {}
            # Return the full context for better Synthesis
            results.append({
                "text": payload.get("parent_section_text", payload.get("content", payload.get("text", ""))),
                "source_page": payload.get("source_page", 1),
                "source_bbox": payload.get("source_bbox", []),
                "document_id": payload.get("document_id", ""),
                "score": getattr(point, "score", None),
            })
            
        return json.dumps(results, indent=2)
    except Exception as e:
        logger.error("Vector query failed", error=str(e))
        return json.dumps({"error": f"Failed to query Vector DB: {e}", "results": []})
