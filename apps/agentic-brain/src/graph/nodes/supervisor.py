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
    Uses the FRONTIER model tier (e.g. GPT-4o) for high-accuracy routing.
    """
    logger.info("Supervisor classifying intent")
    
    llm = LLMFactory.get_llm(tier=ModelTier.FRONTIER)
    structured_llm = llm.with_structured_output(IntentClassification)
    
    system_prompt = state.get("system_prompt")
    if not system_prompt:
        system_prompt = """You are the master routing supervisor for a Tri-Modal AI Brain.
You must classify the user's intent into one or more of these three categories:

1. 'SQL': Exact tabular values from Postgres views OR aggregations via Cube (e.g., "What is the share capital for Infosys BPM?", "What is the total revenue?", "How many invoices were late?"). Prefer SQL whenever numbers or structured table fields matter.
2. 'CYPHER': The user is asking for multi-hop relationships or graph connections (e.g., "Who signed the contract related to this patient?", "How is Company A connected to Bank B?"). This goes to Neo4j.
3. 'VECTOR': The user is asking semantic, unstructured questions (e.g., "Find clauses about late fees", "What did the doctor say in the notes?").

Analyze the user's request, provide reasoning, and output a list of required intents.
For complex or open-ended questions, prefer multiple modalities (e.g., ['SQL', 'VECTOR', 'CYPHER']) so the synthesizer can cross-check tabular, semantic, and graph evidence.
Always include every modality that could contribute useful evidence — do not artificially limit to a single source when more than one applies.
Always include 'SQL' when the answer depends on exact extracted table values.
"""
    else:
        system_prompt = f"""You are a specialized Virtual Employee.
Your role and instructions:
{system_prompt}

Based on the user's request and your instructions, classify the intent into one or more of these three categories:
1. 'SQL': Exact Postgres view rows OR Cube aggregations when numbers/table fields matter.
2. 'CYPHER': For multi-hop relationships or graph connections (Neo4j).
3. 'VECTOR': For semantic, unstructured questions (Qdrant).

Analyze the user's request, provide reasoning, and output a list of required intents.
For complex work tasks, prefer routing to all relevant modalities (['SQL', 'VECTOR', 'CYPHER']) so answers synthesize tabular, vector, and graph evidence.
Always include every modality that could contribute useful evidence.
Always include 'SQL' when the answer depends on exact extracted table values.
"""
    
    user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break
            
    response = structured_llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_msg)
    ])
    
    logger.info("Supervisor Decision", intents=response.intents, reasoning=response.reasoning)
    
    return {
        "required_modalities": response.intents,
        "target_task": "",
        # Do not write retries here — parallel execute nodes increment via operator.add.
        "error_message": "",
    }
