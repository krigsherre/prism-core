import pytest
from langchain_core.messages import HumanMessage
from graph.state import InteractionState
from graph.nodes.supervisor import supervisor_node
from graph.workflow import supervisor_router

@pytest.mark.asyncio
async def test_supervisor_classification():
    state: InteractionState = {
        "messages": [HumanMessage(content="What is the total revenue?")],
        "tenant_id": "test",
        "document_id": "doc_1",
        "is_complex": False,
        "required_modalities": ["SQL"],
        "target_task": "",
        "sql_result": "",
        "cypher_result": "",
        "vector_result": "",
        "retries": 0,
        "error_message": "",
        "final_answer": "",
        "references": []
    }
    
    routes = supervisor_router(state)
    assert "generate_sql" in routes
    assert len(routes) == 1
    state["required_modalities"] = ["SQL", "VECTOR", "CYPHER"]
    routes = supervisor_router(state)
    assert "generate_sql" in routes
    assert "generate_cypher" in routes
    assert "generate_vector" in routes
    assert len(routes) == 3
