import operator
from typing import Annotated, Sequence, TypedDict, List, Optional, Any
from langchain_core.messages import BaseMessage


def _last_nonempty(left: str, right: str) -> str:
    return right if right not in (None, "") else left


def _last_value(left: Any, right: Any) -> Any:
    """Last-write-wins for parallel fan-in of non-reducer scalars."""
    return right if right is not None else left


class InteractionState(TypedDict):
    """
    State for the top-level Interaction Graph (Agentic Brain Supervisor).
    Parallel agent fan-out requires reducers on shared keys (retries/errors/results).
    Nodes that fail should return retries=1 (increment); the reducer sums parallel failures.
    """
    messages: Annotated[Sequence[BaseMessage], operator.add]
    tenant_id: str
    document_id: str
    
    is_complex: bool
    system_prompt: str       
    required_modalities: Annotated[List[str], _last_value]
    target_task: Annotated[str, _last_nonempty]
    sql_query: Annotated[str, _last_nonempty]
    cypher_query: Annotated[str, _last_nonempty]
    vector_query: Annotated[str, _last_nonempty]
    
    sql_result: Annotated[str, _last_nonempty]
    cypher_result: Annotated[str, _last_nonempty]
    vector_result: Annotated[str, _last_nonempty]
    
    retries: Annotated[int, operator.add]
    error_message: Annotated[str, _last_nonempty]
    
    final_answer: Annotated[str, _last_nonempty]
    references: Annotated[List[dict], operator.add]
