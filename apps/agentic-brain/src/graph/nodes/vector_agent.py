import json
import structlog
from pydantic import BaseModel, Field
from llm.factory import LLMFactory, ModelTier
from langchain_core.messages import SystemMessage, HumanMessage
from graph.state import InteractionState
from tools.qdrant_tools import query_vector_db

logger = structlog.get_logger(__name__)

class VectorQueryOutput(BaseModel):
    search_query: str = Field(description="The semantic search query to execute against the vector DB.")

async def generate_vector_node(state: InteractionState) -> dict:
    """
    Generates a semantic search query based on the user's intent.
    """
    logger.info("Generating Vector Query")
    
    llm = LLMFactory.get_llm(tier=ModelTier.STANDARD)
    structured_llm = llm.with_structured_output(VectorQueryOutput)
    
    system_prompt = """You are a Semantic Search Expert.
Extract the core meaning of the user's question to formulate a semantic search query.
Return ONLY the search query string.
"""
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break
            
    response = await structured_llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_msg)
    ])
    
    return {"vector_query": response.search_query}

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
        for c in chunks:
            if not isinstance(c, dict):
                continue
            text = c.get("text") or ""
            if text:
                context_texts.append(text)
            references.append({
                "doc_id": c.get("document_id"),
                "source_page": c.get("source_page"),
                "source_bbox": c.get("source_bbox")
            })
            
        context_str = "\n\n---\n\n".join(context_texts) if context_texts else "(no matching chunks)"
        
        user_msg = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                user_msg = msg.content
                break
                
        llm = LLMFactory.get_llm(tier=ModelTier.STANDARD)
        
        system_prompt = f"""You are an expert Q&A assistant.
Answer the user's question based ONLY on the following context retrieved from semantic search. 
If you cannot answer the question based on the context, say "I don't know based on the provided documents."

<context>
{context_str}
</context>
"""
        
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg)
        ])
        
        return {
            "error_message": "",
            "vector_result": response.content,
            "references": references
        }
        
    except Exception as e:
        logger.error("Vector Tool crashed", error=str(e))
        return {
            "error_message": str(e),
            "retries": 1,
        }
