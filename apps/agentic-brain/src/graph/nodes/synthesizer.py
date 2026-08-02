import structlog
from llm.factory import LLMFactory, ModelTier
from langchain_core.messages import SystemMessage, HumanMessage
from graph.state import InteractionState

logger = structlog.get_logger(__name__)

async def synthesize_node(state: InteractionState) -> dict:
    """
    Takes the output of all executed parallel branches and synthesizes a final, highly accurate answer.
    """
    logger.info("Synthesizing parallel RAG data")
    
    sql_data = state.get("sql_result", "")
    cypher_data = state.get("cypher_result", "")
    vector_data = state.get("vector_result", "")
    references = state.get("references", []) or []
    
    llm = LLMFactory.get_llm(tier=ModelTier.FRONTIER)
    
    system_prompt = """You are a master data synthesizer for a Tri-Modal AI Brain.
You have been given raw data from up to three distinct sources:
1. SQL / Postgres (exact extracted table rows from views, plus Cube aggregations when present)
2. Graph Database (Relationships, nodes, edges)
3. Vector Database (Unstructured text, clauses)

Your job is to read the user's intent and synthesize all the provided data into a cohesive, highly accurate, beautifully formatted markdown response.
When SQL exact-row data conflicts with vector text, prefer the SQL/Postgres extracted values for numbers and structured fields.
If SQL data is marked provisional / NEEDS_REVIEW / data_quality=provisional, still use it when it is the best available evidence, but state that figures are provisional pending review.
Prefer verified/MAPPED SQL values over provisional ones when both appear.
If a data source is empty, ignore it.
Do NOT mention the databases (e.g. "The graph database says..."). Just provide the synthesized facts.
When provenance references are provided, include markdown citation links using the exact href format given.
"""
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break
            
    prompt_context = f"User Intent: {user_msg}\n\n"
    
    if sql_data:
        prompt_context += f"--- Tabular Data ---\n{sql_data}\n\n"
    if cypher_data:
        prompt_context += f"--- Relationship Data ---\n{cypher_data}\n\n"
    if vector_data:
        prompt_context += f"--- Semantic Excerpts ---\n{vector_data}\n\n"

    citation_lines = []
    for i, ref in enumerate(references, start=1):
        doc_id = ref.get("doc_id") or ref.get("document_id") or "document"
        page = ref.get("source_page") or 1
        bbox = ref.get("source_bbox") or [0, 0, 0, 0]
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            bbox_str = ",".join(str(v) for v in bbox[:4])
        else:
            bbox_str = "0,0,0,0"
        href = f"{doc_id}#page={page}&bbox={bbox_str}"
        citation_lines.append(f"[{i}]({href}) (page {page})")
    if citation_lines:
        prompt_context += "--- Provenance Citations ---\n" + "\n".join(citation_lines) + "\n\n"
        
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt_context)
    ])
    
    return {"final_answer": response.content}
