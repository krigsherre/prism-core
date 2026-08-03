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

def supervisor_node(state: InteractionState) -> dict:
    """
    Analyzes the user's latest message and decides which sub-agent (SQL, Cypher, Vector) should handle it.
    Uses fast pattern matching and LIGHT tier model for ultra-low latency routing (<100ms).
    """
    logger.info("Supervisor classifying intent")
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    # Fast heuristic routing for instant performance (<10ms)
    lower_msg = user_msg.lower()
    intents = []
    if any(kw in lower_msg for kw in ["revenue", "income", "asset", "liability", "equity", "tax", "fee", "amount", "total", "ratio", "balance", "sheet", "profit", "cash", "share", "number", "how many", "%", "$"]):
        intents.append("SQL")
    if any(kw in lower_msg for kw in ["who", "auditor", "director", "owner", "signed", "party", "relation", "parent", "subsidiary", "vendor", "client", "connected"]):
        intents.append("CYPHER")
    if any(kw in lower_msg for kw in ["clause", "note", "disclosure", "item", "report", "policy", "statement", "what", "find", "explain", "describe", "summary", "read"]):
        intents.append("VECTOR")
        
    if not intents:
        intents = ["SQL", "VECTOR", "CYPHER"]

    reasoning = f"Fast-path tri-modal routing for keywords: {intents}"

    logger.info("Supervisor Decision", intents=intents, reasoning=reasoning)
    
    return {
        "required_modalities": intents,
        "target_task": "",
        "error_message": "",
    }
