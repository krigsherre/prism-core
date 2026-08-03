"""LangGraph compilation with durable Postgres checkpoints (MemorySaver fallback)."""
from __future__ import annotations

import structlog
from typing import Literal, List, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from graph.state import InteractionState
from graph.nodes.supervisor import supervisor_node
from graph.nodes.sql_agent import generate_sql_node, execute_sql_node
from graph.nodes.cypher_agent import generate_cypher_node, execute_cypher_node
from graph.nodes.vector_agent import generate_vector_node, execute_vector_node
from graph.nodes.synthesizer import synthesize_node
from graph.nodes.employee_critic import employee_critic_node

logger = structlog.get_logger(__name__)


brain_graph = None
_checkpointer_cm = None
_checkpointer = None


def should_retry(state: InteractionState) -> Literal["retry", "end"]:
    if state.get("error_message") and state.get("retries", 0) < 3:
        return "retry"
    return "end"


def supervisor_router(state: InteractionState) -> List[str]:
    """Returns a list of nodes to execute in parallel based on required modalities."""
    routes = []
    modalities = state.get("required_modalities", [])

    if "SQL" in modalities:
        routes.append("generate_sql")
    if "CYPHER" in modalities:
        routes.append("generate_cypher")
    if "VECTOR" in modalities:
        routes.append("generate_vector")

    if not routes:
        logger.warning("No route found, defaulting to vector")
        routes.append("generate_vector")

    return routes


def build_workflow() -> StateGraph:
    workflow = StateGraph(InteractionState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("execute_sql", execute_sql_node)
    workflow.add_node("generate_cypher", generate_cypher_node)
    workflow.add_node("execute_cypher", execute_cypher_node)
    workflow.add_node("generate_vector", generate_vector_node)
    workflow.add_node("execute_vector", execute_vector_node)
    workflow.add_node("synthesizer", synthesize_node)
    workflow.add_node("employee_critic", employee_critic_node)

    workflow.set_entry_point("supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "generate_sql": "generate_sql",
            "generate_cypher": "generate_cypher",
            "generate_vector": "generate_vector",
        },
    )

    workflow.add_edge("generate_sql", "execute_sql")
    workflow.add_conditional_edges(
        "execute_sql",
        should_retry,
        {"retry": "generate_sql", "end": "synthesizer"},
    )

    workflow.add_edge("generate_cypher", "execute_cypher")
    workflow.add_conditional_edges(
        "execute_cypher",
        should_retry,
        {"retry": "generate_cypher", "end": "synthesizer"},
    )

    workflow.add_edge("generate_vector", "execute_vector")
    workflow.add_conditional_edges(
        "execute_vector",
        should_retry,
        {"retry": "generate_vector", "end": "synthesizer"},
    )
    workflow.add_edge("synthesizer", "employee_critic")
    workflow.add_edge("employee_critic", END)
    return workflow


def create_agentic_brain_graph(checkpointer: Any = None):
    """Compiles the Tri-Modal RAG StateGraph with the given checkpointer."""
    workflow = build_workflow()
    if checkpointer is None:
        checkpointer = MemorySaver()
        logger.warning("Compiling brain_graph with in-memory MemorySaver (not durable across replicas)")
    compiled = workflow.compile(checkpointer=checkpointer)
    return compiled


async def init_brain_graph(database_url: str) -> Any:
    """
    Initialize durable Postgres checkpointer and compile brain_graph.
    Falls back to MemorySaver if Postgres checkpoint setup fails.
    """
    global brain_graph, _checkpointer_cm, _checkpointer

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(database_url)
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()
        brain_graph = create_agentic_brain_graph(_checkpointer)
        logger.info("brain_graph compiled with AsyncPostgresSaver checkpoints")
        return brain_graph
    except Exception as e:
        logger.error("Failed to init Postgres checkpointer; falling back to MemorySaver", error=str(e))
        brain_graph = create_agentic_brain_graph(MemorySaver())
        return brain_graph


async def close_brain_graph() -> None:
    global brain_graph, _checkpointer_cm, _checkpointer
    if _checkpointer_cm is not None:
        try:
            await _checkpointer_cm.__aexit__(None, None, None)
        except Exception as e:
            logger.warning("Error closing checkpointer", error=str(e))
    _checkpointer_cm = None
    _checkpointer = None
    brain_graph = None


def get_brain_graph():
    """Return the compiled graph; lazy MemorySaver compile if startup has not run."""
    global brain_graph
    if brain_graph is None:
        brain_graph = create_agentic_brain_graph(MemorySaver())
    return brain_graph


brain_graph = create_agentic_brain_graph(MemorySaver())
