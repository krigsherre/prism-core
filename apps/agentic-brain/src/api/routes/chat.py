import structlog
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from api.middleware.auth import get_tenant_from_token
from graph.workflow import get_brain_graph

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    thread_id: str
    message: str
    document_id: str = ""
    agent_role: str = "research_assistant"

NODE_STEP_MAPPING = {
    "supervisor": "🔍 Analyzing intent & routing across SQL, Vector, and Graph RAG",
    "generate_sql": "📋 Planning SQL query against standardized Postgres financial views",
    "execute_sql": "⚡ Executing read-only Postgres view query",
    "generate_vector": "🔎 Formulating semantic search query for vector embeddings",
    "execute_vector": "📚 Querying Qdrant vector database for document disclosures",
    "generate_cypher": "🕸️ Inspecting Neo4j ontology & building Cypher graph query",
    "execute_cypher": "🔗 Executing Cypher query on Neo4j corporate graph",
    "synthesizer": "🧠 Synthesizing evidence across SQL, Vector, and Graph into audit report",
    "employee_critic": "🛡️ Self-verifying assertions & applying audit verification seal",
}

@router.post("")
async def chat(req: ChatRequest, tenant_id: str = Depends(get_tenant_from_token)):
    """Enterprise Tri-Modal RAG Chat Endpoint with Streaming and Auth."""
    logger.info("Received chat request", tenant=tenant_id, thread_id=req.thread_id, document_id=req.document_id, agent_role=req.agent_role)
    
    config = {"configurable": {"thread_id": req.thread_id}}
    brain_graph = get_brain_graph()
    
    async def event_generator():
        # Yield explicit thinking event for TTFT <200ms
        init_thinking = json.dumps({'type': 'thinking', 'content': f'Analyzing query intent across SQL, Vector, and Graph for {req.agent_role}...'})
        yield f"data: {init_thinking}\n\n"
        
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "tenant_id": tenant_id,
            "document_id": req.document_id or "",
            "is_complex": False,
            "system_prompt": "",
            "required_modalities": [],
            "intent": "",
            "target_task": req.agent_role,
            "sql_query": "",
            "cypher_query": "",
            "vector_query": "",
            "sql_result": "",
            "cypher_result": "",
            "vector_result": "",
            "retries": 0,
            "error_message": "",
            "final_answer": "",
            "references": []
        }
        
        last_final_answer = ""
        last_references = []

        try:
            async for event in brain_graph.astream_events(initial_state, config, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk_obj = event.get("data", {}).get("chunk")
                    if chunk_obj:
                        chunk_content = getattr(chunk_obj, "content", "")
                        # Handle string content or reasoning content
                        if isinstance(chunk_content, list):
                            text_bits = [c.get("text", "") for c in chunk_content if isinstance(c, dict) and c.get("text")]
                            chunk_content = "".join(text_bits)
                        if chunk_content:
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk_content})}\n\n"
                elif kind == "on_chain_start":
                    node_name = event.get("name")
                    if node_name and node_name in NODE_STEP_MAPPING:
                        yield f"data: {json.dumps({'type': 'status', 'content': NODE_STEP_MAPPING[node_name]})}\n\n"
                elif kind == "on_chain_end":
                    output = event.get("data", {}).get("output")
                    if isinstance(output, dict):
                        if output.get("final_answer"):
                            last_final_answer = output.get("final_answer")
                        if output.get("references"):
                            last_references = output.get("references")
                
            if not last_final_answer:
                final_state = await brain_graph.aget_state(config)
                if final_state and final_state.values:
                    vals = final_state.values
                    last_final_answer = vals.get('final_answer', '')
                    if not last_references:
                        last_references = vals.get('references', [])

            yield f"data: {json.dumps({'type': 'message_complete', 'content': last_final_answer})}\n\n"
            yield f"data: {json.dumps({'type': 'references', 'content': last_references})}\n\n"
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Graph execution failed", error=str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e) or repr(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")
