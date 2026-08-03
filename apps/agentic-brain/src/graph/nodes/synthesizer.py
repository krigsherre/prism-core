from core.db import structlog
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
    
    document_id = state.get("document_id")
    doc_context = f"Target Document: {document_id}" if document_id else "Target Document: ALL (Global Knowledge Base)"
    
    system_prompt = f"""You are a master data synthesizer and intelligent financial assistant for Agentic Brain.
You have been given raw data from up to three distinct sources:
1. SQL / Postgres (exact extracted table rows from views, multi-table queries, plus Cube aggregations & ratios when present)
2. Graph Database (Relationships, nodes, edges)
3. Vector Database (Unstructured text, clauses)

Your job is to read the user's intent and synthesize a cohesive, highly accurate, beautifully formatted markdown response.

PROVENANCE & PROXY GUIDELINES:
- {doc_context}
- EXECUTIVE TONE MANDATE: Be confident, direct, and executive. NEVER write defensive disclaimers, "Data Quality Notice", "Data Extraction Status Summary", or "Data Limitation Notice" sections. NEVER complain about unpopulated dictionary keys or pipeline status.
- HYBRID RAG MANDATE: If SQL tabular columns contain null values for numeric metrics, pull any quantitative numbers directly from the Semantic Excerpts (Vector Database text chunks) and synthesize them seamlessly into clean markdown tables with page citations.
- Focus 100% on synthesizing and presenting the valuable facts, metrics, section schedules, and disclosures that ARE retrieved in clear markdown.
- When retrieved RAG data is present, synthesize all provided facts accurately. When SQL exact-row data conflicts with vector text, prefer the SQL/Postgres extracted values for numbers.
- PROVENANCE MANDATE: ALWAYS mention the source document name, company, and page number when reporting tabular metrics (e.g. "According to **Apple Inc. FY2024 10-K** (Page 42)...").
- PROXY TRANSPARENCY: If a metric was calculated or derived from adjacent fields (e.g. Subtotal = Total - Tax), explicitly disclose the proxy formula in your answer (e.g. "Subtotal: $900 (derived from Total $1,000 minus Tax $100)").
- CITATIONS: When provenance references are provided, include markdown citation links using the exact href format given.
- If the retrieved RAG data is empty or insufficient, OR if the user's question is a general query, concept explanation, greeting, or financial definition (e.g., "What is Interest Coverage Ratio?", "Hello", "How to calculate EBITDA"), answer the question directly, thoroughly, and helpfully using your general knowledge.
- Do NOT mention internal database table names (e.g. "view_standardized_balance_sheet"). Render clean financial tables with professional column titles.
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
        bbox = ref.get("source_bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4 and any(v != 0 for v in bbox[:4]):
            bbox_str = ",".join(str(v) for v in bbox[:4])
            href = f"{doc_id}#page={page}&bbox={bbox_str}"
        else:
            href = f"{doc_id}#page={page}"
        citation_lines.append(f"[{i}]({href}) (page {page})")
    if citation_lines:
        prompt_context += "--- Provenance Citations ---\n" + "\n".join(citation_lines) + "\n\n"
        
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt_context)
    ])
    
    return {"final_answer": response.content}
