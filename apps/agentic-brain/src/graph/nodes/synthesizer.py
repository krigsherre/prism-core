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
- STRICT NO-DISCLAIMER MANDATE: Be confident, direct, and executive. NEVER write disclaimers like "data contains null values", "unable to calculate at this time", "all line items null", or "extraction returned empty numeric fields".
- STRICT NO-TROUBLESHOOTING MANDATE: NEVER output "Recommended Next Steps", "Verify Document Ingestion", "Check OCR/extraction pipeline", "Request manual review", or pipeline escalation messages. Focus 100% on executive financial metrics, calculations, ratios, and factual insights.
- STRICT NO-PROVENANCE-SECTION MANDATE: NEVER write or append a manual "Source Provenance", "References", or "Page X" list section at the bottom of your response. The chat UI automatically renders interactive provenance buttons from system metadata.
- MANDATORY METRIC & PROXY CALCULATIONS: Showcase all financial metrics, balance sheets, income statements, and cash flows directly. If a requested metric (e.g. EBIT, Interest Expense, Cash, Short-Term Debt) is not explicitly populated in the SQL columns, derive proxy values from adjacent same-row fields (e.g. EBIT = Operating Income, or Gross Profit minus Opex, or Total Revenue minus COGS minus Opex) OR extract quantitative figures directly from the Semantic Excerpts (Vector text chunks).
- Always compute and present the requested ratios and financial analysis in clean markdown tables. Explicitly disclose proxy methods in footnote annotations (e.g., "*EBIT derived from Operating Income $114,301M").
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

    seen_citations = set()
    deduped_references = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        doc_id = ref.get("doc_id") or ref.get("document_id") or "document"
        raw_page = ref.get("source_page") or ref.get("page") or ref.get("page_number")
        try:
            page = int(raw_page) if raw_page is not None else 1
        except (ValueError, TypeError):
            page = 1
            
        cit_key = (doc_id, page)
        if cit_key in seen_citations:
            continue
        seen_citations.add(cit_key)
        deduped_references.append({
            "doc_id": doc_id,
            "document_id": doc_id,
            "source_page": page,
            "page": page,
            "source_bbox": ref.get("source_bbox") or ref.get("bbox") or []
        })

    citation_lines = []
    for idx, ref in enumerate(deduped_references, start=1):
        doc_id = ref["doc_id"]
        page = ref["source_page"]
        bbox = ref["source_bbox"]
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4 and any(v != 0 for v in bbox[:4]):
            bbox_str = ",".join(str(v) for v in bbox[:4])
            href = f"{doc_id}#page={page}&bbox={bbox_str}"
        else:
            href = f"{doc_id}#page={page}"
        citation_lines.append(f"[{idx}]({href}) (page {page})")

    if citation_lines:
        prompt_context += "--- Provenance Citations ---\n" + "\n".join(citation_lines) + "\n\n"
        
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt_context)
    ])
    
    return {
        "final_answer": response.content,
        "references": deduped_references
    }
