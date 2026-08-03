import structlog
from pydantic import BaseModel, Field
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage
from graph.state import InteractionState
from llm.factory import LLMFactory, ModelTier

logger = structlog.get_logger(__name__)

class IntentClassification(BaseModel):
    intents: List[str] = Field(description="List of intents. Can include 'SQL', 'CYPHER', 'VECTOR'.")
    reasoning: str = Field(description="Brief explanation of why these intents were chosen based on the user's question.")

async def supervisor_node(state: InteractionState) -> dict:
    """
    Analyzes the user's latest message and decides which sub-agent (SQL, Cypher, Vector) should handle it.
    Uses Frontier LLM for high-accuracy intent classification.
    """
    logger.info("Supervisor classifying intent")
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    from core.db import db_client
    tenant_id = state.get("tenant_id", "default-tenant")
    docs = await db_client.fetch_tenant_documents(tenant_id)
    doc_catalog = "\n".join([
        f"- [ID: {d['document_id']}] File: {d['filename']} | Company: {d.get('company_name')} ({d.get('ticker')}) | Period: {d.get('fiscal_period')}"
        for d in docs
    ])
    
    llm = LLMFactory.get_structured_llm(IntentClassification, ModelTier.FRONTIER)
    
    document_id = state.get("document_id")
    doc_context = f"Target Document: {document_id}" if document_id else "Target Document: ALL (Global Knowledge Base)"

    system_prompt = f"""You are an intelligent supervisor for a Tri-Modal RAG system.
Your job is to read the user's query and decide which data sources are needed.
Select from these available intents:
- 'SQL': For exact numbers, revenue, profit, tables, balance sheets, ratios.
- 'CYPHER': For relationships, subsidiaries, key personnel, auditors, parent companies.
- 'VECTOR': For qualitative text, disclosures, policies, explanations, summaries, OR if the user is asking about a specific company/entity by name and we need to find the relevant document context.

AVAILABLE DOCUMENTS IN KNOWLEDGE BASE (Use this list to recognize company names/tickers the user might be asking about):
{doc_catalog}

CRITICAL RULES:
- {doc_context}
- You can select multiple intents.
- If the user asks about a specific company, entity, or document by name (e.g., 'Apple', 'Acme'), you MUST INCLUDE 'VECTOR' to retrieve the relevant textual context, and you should also include SQL/CYPHER if they ask for numbers or relationships.
- If the query is a general greeting or non-financial question, return an empty list or just 'VECTOR'.
"""
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt, additional_kwargs={"cache_control": {"type": "ephemeral"}}),
            HumanMessage(content=user_msg)
        ])
        
        intents = response.intents if response and response.intents else ["VECTOR"]
        reasoning = response.reasoning if response else "Fallback"
    except Exception as e:
        logger.error("Supervisor LLM failed", error=str(e))
        intents = ["SQL", "VECTOR", "CYPHER"]
        reasoning = "Fallback due to LLM error"

    valid_intents = [i.upper() for i in intents if i.upper() in ["SQL", "CYPHER", "VECTOR"]]
    if not valid_intents:
        valid_intents = ["VECTOR"]

    logger.info("Supervisor Decision", intents=valid_intents, reasoning=reasoning)
    
    return {
        "required_modalities": valid_intents,
        "target_task": "",
        "error_message": "",
    }
