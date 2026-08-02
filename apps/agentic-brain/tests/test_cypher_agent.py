import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
async def test_generate_cypher_returns_cypher_query():
    from graph.nodes.cypher_agent import generate_cypher_node

    mock_response = MagicMock()
    mock_response.cypher = "MATCH (n) RETURN n LIMIT 5"

    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=mock_response)

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.nodes.cypher_agent.fetch_neo4j_schema") as mock_fetch, \
         patch("graph.nodes.cypher_agent.LLMFactory.get_llm", return_value=mock_llm):
        mock_fetch.ainvoke = AsyncMock(return_value="Nodes: Entity")
        state = {
            "messages": [HumanMessage(content="Who is connected to Acme?")],
            "tenant_id": "default-tenant",
            "retries": 0,
            "error_message": "",
        }
        result = await generate_cypher_node(state)

    assert result["cypher_query"] == "MATCH (n) RETURN n LIMIT 5"
    assert "final_answer" not in result


@pytest.mark.asyncio
async def test_execute_cypher_sets_cypher_result():
    from graph.nodes.cypher_agent import execute_cypher_node

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Acme is linked to Bank B."))

    with patch("graph.nodes.cypher_agent.execute_cypher") as mock_exec, \
         patch("graph.nodes.cypher_agent.LLMFactory.get_llm", return_value=mock_llm):
        mock_exec.ainvoke = AsyncMock(return_value='[{"n": "Acme"}]')
        state = {
            "messages": [HumanMessage(content="Who is connected to Acme?")],
            "tenant_id": "default-tenant",
            "cypher_query": "MATCH (n) RETURN n",
            "retries": 0,
        }
        result = await execute_cypher_node(state)

    assert result["cypher_result"] == "Acme is linked to Bank B."
    assert result.get("error_message") == ""
    assert "final_answer" not in result


def test_supervisor_router_all_three_modalities():
    from graph.workflow import supervisor_router

    state = {"required_modalities": ["SQL", "VECTOR", "CYPHER"]}
    routes = supervisor_router(state)
    assert routes == ["generate_sql", "generate_cypher", "generate_vector"]


def test_retries_channel_is_reducer():
    """Parallel execute failures must merge retries — LastValue would raise at runtime."""
    import operator
    import typing
    from graph.state import InteractionState

    hints = typing.get_type_hints(InteractionState, include_extras=True)
    retries = hints["retries"]
    assert typing.get_origin(retries) is typing.Annotated
    assert typing.get_args(retries)[1] is operator.add
