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

@router.post("")
async def chat(req: ChatRequest, tenant_id: str = Depends(get_tenant_from_token)):
    """Enterprise Tri-Modal RAG Chat Endpoint with Streaming and Auth."""
    logger.info("Received chat request", tenant=tenant_id, thread_id=req.thread_id, document_id=req.document_id)
    
    config = {"configurable": {"thread_id": req.thread_id}}
    brain_graph = get_brain_graph()
    
    async def event_generator():
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "tenant_id": tenant_id,
            "document_id": req.document_id or "",
            "is_complex": False,
            "system_prompt": "",
            "required_modalities": [],
            "intent": "",
            "target_task": "",
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
        
        try:
            async for event in brain_graph.astream_events(initial_state, config, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if chunk:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                elif kind == "on_chain_start":
                    node_name = event.get("name")
                    if node_name and node_name not in ["LangGraph", "__start__"]:
                        yield f"data: {json.dumps({'type': 'status', 'content': f'Running {node_name}...'})}\n\n"
                
            final_state = await brain_graph.aget_state(config)
            if final_state and final_state.values:
                vals = final_state.values
                yield f"data: {json.dumps({'type': 'message_complete', 'content': vals.get('final_answer', '')})}\n\n"
                yield f"data: {json.dumps({'type': 'references', 'content': vals.get('references', [])})}\n\n"
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Graph execution failed", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")
