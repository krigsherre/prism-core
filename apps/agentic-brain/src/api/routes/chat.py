import structlog
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from api.middleware.auth import get_tenant_from_token
from graph.workflow import get_brain_graph
from core.db import db_client
import asyncio

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
        
        audit_sql_accessed = False
        audit_vector_accessed = False
        audit_graph_accessed = False
        audit_input_tokens = 0
        audit_output_tokens = 0
        audit_llm_traces = []
        current_llm_trace = {}

        try:
            async for event in brain_graph.astream_events(initial_state, config, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk_obj = event.get("data", {}).get("chunk")
                    if chunk_obj:
                        chunk_content = getattr(chunk_obj, "content", "")
                        if isinstance(chunk_content, list):
                            text_bits = [c.get("text", "") for c in chunk_content if isinstance(c, dict) and c.get("text")]
                            chunk_content = "".join(text_bits)
                        if chunk_content:
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk_content})}\n\n"
                elif kind == "on_chain_start":
                    node_name = event.get("name")
                    if node_name == "execute_sql": audit_sql_accessed = True
                    if node_name == "execute_vector": audit_vector_accessed = True
                    if node_name == "execute_cypher": audit_graph_accessed = True
                    if node_name and node_name in NODE_STEP_MAPPING:
                        yield f"data: {json.dumps({'type': 'status', 'content': NODE_STEP_MAPPING[node_name]})}\n\n"
                elif kind == "on_chat_model_start":
                    input_data = event.get("data", {}).get("input")
                    if isinstance(input_data, dict) and "messages" in input_data:
                        try:
                            prompt_text = "\n".join([m.content for m in input_data["messages"] if hasattr(m, "content") and isinstance(m.content, str)])
                            current_llm_trace = {"prompt": prompt_text, "response": ""}
                        except Exception:
                            pass
                elif kind == "on_chat_model_end":
                    output_msg = event.get("data", {}).get("output")
                    if output_msg:
                        try:
                            content = getattr(output_msg, "content", "")
                            if isinstance(content, list):
                                content = "".join([c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")])
                            if current_llm_trace:
                                current_llm_trace["response"] = content
                                audit_llm_traces.append(current_llm_trace)
                                current_llm_trace = {}
                        except Exception:
                            pass
                        
                        usage = getattr(output_msg, "usage_metadata", None)
                        if not usage:
                            rm = getattr(output_msg, "response_metadata", {})
                            usage = rm.get("token_usage", rm.get("usage", {}))
                        
                        if usage:
                            audit_input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0))
                            audit_output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0))
                elif kind == "on_chain_end":
                    output = event.get("data", {}).get("output")
                    if isinstance(output, dict):
                        if output.get("final_answer"):
                            last_final_answer = output.get("final_answer")
                        if output.get("references"):
                            last_references = output.get("references")
                
            clean_refs = []
            seen_ref_keys = set()
            for r in (last_references or []):
                if not isinstance(r, dict):
                    continue
                d_id = r.get("doc_id") or r.get("document_id") or ""
                r_pg = r.get("source_page") or r.get("page") or r.get("page_number") or 1
                try:
                    p_num = int(r_pg)
                except (ValueError, TypeError):
                    p_num = 1
                rk = (d_id, p_num)
                if rk not in seen_ref_keys:
                    seen_ref_keys.add(rk)
                    clean_refs.append(r)
            last_references = clean_refs

            yield f"data: {json.dumps({'type': 'message_complete', 'content': last_final_answer})}\n\n"
            yield f"data: {json.dumps({'type': 'references', 'content': last_references})}\n\n"
            yield "data: [DONE]\n\n"
            
            asyncio.create_task(db_client.insert_chat_audit_log({
                "tenant_id": tenant_id,
                "thread_id": req.thread_id,
                "document_id": req.document_id,
                "user_message": req.message,
                "agent_response": last_final_answer,
                "sql_accessed": audit_sql_accessed,
                "vector_accessed": audit_vector_accessed,
                "graph_accessed": audit_graph_accessed,
                "llm_traces": audit_llm_traces,
                "input_tokens": audit_input_tokens,
                "output_tokens": audit_output_tokens
            }))
            
            
        except Exception as e:
            logger.error("Graph execution failed", error=str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e) or repr(e)})}\n\n"
            
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
