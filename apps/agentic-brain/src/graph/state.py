import operator
from typing import Annotated, Sequence, TypedDict, List, Optional, Any
from langchain_core.messages import BaseMessage


def _last_nonempty(left: str, right: str) -> str:
    return right if right not in (None, "") else left


def _last_value(left: Any, right: Any) -> Any:
    """Last-write-wins for parallel fan-in of non-reducer scalars."""
    return right if right is not None else left


def _dedup_references(left: List[dict], right: List[dict]) -> List[dict]:
    """Combines and deduplicates reference lists by (doc_id, page_number)."""
    combined = (left or []) + (right or [])
    deduped = []
    seen = set()
    for ref in combined:
        if not isinstance(ref, dict):
            continue
        d_id = ref.get("doc_id") or ref.get("document_id") or ""
        r_pg = ref.get("source_page") or ref.get("page") or ref.get("page_number") or 1
        try:
            p_num = int(r_pg)
        except (ValueError, TypeError):
            p_num = 1
        key = (d_id, p_num)
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    return deduped


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
    references: Annotated[List[dict], _dedup_references]
