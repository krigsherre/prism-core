"""LangGraph compilation with durable Postgres checkpoints and modular workflow engine."""
from __future__ import annotations

from typing import Any, List, Literal, Optional

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from graph.nodes.cypher_agent import execute_cypher_node, generate_cypher_node
from graph.nodes.employee_critic import employee_critic_node
from graph.nodes.sql_agent import execute_sql_node, generate_sql_node
from graph.nodes.supervisor import supervisor_node
from graph.nodes.synthesizer import synthesize_node
from graph.nodes.vector_agent import execute_vector_node, generate_vector_node
from graph.state import InteractionState

logger = structlog.get_logger(__name__)


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


class BrainGraphEngine:
    """Manager class for configuring, compiling, and initializing the Tri-Modal RAG graph."""

    def __init__(self) -> None:
        self.brain_graph: Any = None
        self._checkpointer_cm: Any = None
        self._checkpointer: Any = None

    def build_workflow(self) -> StateGraph:
        """Construct the StateGraph DAG structure."""
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

    def create_graph(self, checkpointer: Any = None) -> Any:
        """Compile the workflow graph using checkpointer."""
        workflow = self.build_workflow()
        if checkpointer is None:
            checkpointer = MemorySaver()
            logger.warning("Compiling brain_graph with in-memory MemorySaver (not durable across replicas)")
        return workflow.compile(checkpointer=checkpointer)

    async def init(self, database_url: str) -> Any:
        """Initialize Postgres checkpointer and compile brain_graph."""
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            self._checkpointer_cm = AsyncPostgresSaver.from_conn_string(database_url)
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            await self._checkpointer.setup()
            self.brain_graph = self.create_graph(self._checkpointer)
            logger.info("brain_graph compiled with AsyncPostgresSaver checkpoints")
            return self.brain_graph
        except Exception as e:
            logger.error("Failed to init Postgres checkpointer; falling back to MemorySaver", error=str(e))
            self.brain_graph = self.create_graph(MemorySaver())
            return self.brain_graph

    async def close(self) -> None:
        """Close checkpointer resources."""
        if self._checkpointer_cm is not None:
            try:
                await self._checkpointer_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing checkpointer", error=str(e))
        self._checkpointer_cm = None
        self._checkpointer = None
        self.brain_graph = None

    def get(self) -> Any:
        """Return lazy-compiled or initialized graph instance."""
        if self.brain_graph is None:
            self.brain_graph = self.create_graph(MemorySaver())
        return self.brain_graph


_engine = BrainGraphEngine()


def build_workflow() -> StateGraph:
    return _engine.build_workflow()


def create_agentic_brain_graph(checkpointer: Any = None):
    return _engine.create_graph(checkpointer)


async def init_brain_graph(database_url: str) -> Any:
    return await _engine.init(database_url)


async def close_brain_graph() -> None:
    await _engine.close()


def get_brain_graph():
    return _engine.get()
