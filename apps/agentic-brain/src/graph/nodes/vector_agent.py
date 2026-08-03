import json
import structlog
from pydantic import BaseModel, Field
from llm.factory import LLMFactory, ModelTier
from langchain_core.messages import SystemMessage, HumanMessage
from graph.state import InteractionState
from tools.qdrant_tools import query_vector_db
from langchain_core.output_parsers import PydanticOutputParser

logger = structlog.get_logger(__name__)

class VectorQueryOutput(BaseModel):
    search_query: str = Field(description="The semantic search query to execute against the vector DB.")

async def generate_vector_node(state: InteractionState) -> dict:
    """
    Generates a semantic search query based on the user's intent.
    Uses Frontier LLM for generating an optimized semantic query.
    """
    logger.info("Generating Vector Query")
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break
            
    llm = LLMFactory.get_structured_llm(VectorQueryOutput, ModelTier.FRONTIER)
    system_prompt = """You are an expert search query generator for Agentic Brain.
Given the user's question, generate the optimal semantic search string to query the Qdrant vector database.
- Strip out conversational filler (e.g. 'Can you tell me about').
- Focus on the core keywords, concepts, and entities.
- If they ask about specific disclosures, policies, or risks, include those terms in the query.
"""
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg)
        ])
        vector_query = response.search_query or user_msg
    except Exception as e:
        logger.error("Vector Planner LLM failed", error=str(e))
        vector_query = user_msg

    return {"vector_query": vector_query}

async def execute_vector_node(state: InteractionState) -> dict:
    """
    Executes the semantic search query and returns the context with provenance.
    """
    query_to_run = state.get("vector_query", "")
    tenant_id = state.get("tenant_id", "default-tenant")
    document_id = state.get("document_id")
    logger.info("Executing Vector Search", search=query_to_run)
    
    try:
        result_json = await query_vector_db.ainvoke({
            "query": query_to_run, 
            "tenant_id": tenant_id,
            "document_id": document_id
        })
        
        parsed = json.loads(result_json)
        if isinstance(parsed, dict) and parsed.get("error"):
            logger.warning("Vector query returned error", error=parsed["error"])
            return {
                "error_message": parsed["error"],
                "vector_result": "No vector context available.",
                "retries": 1,
            }
        chunks = parsed if isinstance(parsed, list) else parsed.get("results") or []
        
        references = []
        context_texts = []
        seen = set()
        for c in chunks:
            if not isinstance(c, dict):
                continue
            text = c.get("text") or ""
            if text:
                context_texts.append(text)
            doc_id = c.get("document_id") or c.get("doc_id")
            raw_page = c.get("source_page") or c.get("page_number") or c.get("page")
            try:
                page = int(raw_page) if raw_page is not None else 1
            except (ValueError, TypeError):
                page = 1
            bbox = c.get("source_bbox") or c.get("bbox") or []
            if doc_id:
                key = (doc_id, page)
                if key not in seen:
                    seen.add(key)
                    references.append({
                        "doc_id": doc_id,
                        "document_id": doc_id,
                        "source_page": page,
                        "page": page,
                        "source_bbox": bbox
                    })
            
        context_str = "\n\n---\n\n".join(context_texts) if context_texts else "(no matching chunks)"
        
        return {
            "error_message": "",
            "vector_result": context_str,
            "references": references
        }
        
    except Exception as e:
        logger.error("Vector Tool crashed", error=str(e))
        return {
            "error_message": str(e),
            "retries": 1,
        }
