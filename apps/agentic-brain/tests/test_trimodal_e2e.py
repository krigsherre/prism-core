import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage

from tools.postgres_tools import list_exact_views, select_by_mapping_priority
from graph.nodes.supervisor import supervisor_node, IntentClassification
from graph.nodes.sql_agent import generate_sql_node, execute_sql_node, SQLPlanOutput
from graph.nodes.vector_agent import generate_vector_node, execute_vector_node, VectorQueryOutput
from graph.nodes.cypher_agent import generate_cypher_node, execute_cypher_node, CypherTemplateSelection
from graph.workflow import supervisor_router


@pytest.mark.asyncio
async def test_trimodal_ingestion_and_chat_routing():
    """
    End-to-End Unit & Integration Test for Tri-Modal RAG (SQL + Vector + Graph).
    Simulates data ingestion across PostgreSQL, Qdrant, and Neo4j,
    then verifies Supervisor routing and multi-agent Chat node execution.
    """
    # 1. Verify SQL Modality Mapping Priority Logic
    mock_extracted_rows = [
        {
            "id": "row-001",
            "sys_document_id": "doc-acme-10k",
            "sys_node_id": "node-001",
            "tenant_id": "default-tenant",
            "target_table": "standardized_balance_sheet",
            "mapping_status": "MAPPED",
            "company_name": "Acme Corp",
            "fiscal_year": "2025",
            "total_assets": 5000000,
            "total_liabilities": 2000000,
            "total_equity": 3000000,
            "source_page": 4,
            "source_bbox": [10, 20, 100, 200]
        }
    ]
    selected, trust = select_by_mapping_priority(mock_extracted_rows)
    assert trust == "verified"
    assert len(selected) == 1
    assert selected[0]["company_name"] == "Acme Corp"
    assert selected[0]["total_assets"] == 5000000

    # 2. Verify Supervisor Intent Classification Routing
    mock_supervisor_out = IntentClassification(
        intents=["SQL", "VECTOR", "CYPHER"],
        reasoning="Query asks for tabular financial metrics, semantic disclosures, and auditor relationships."
    )
    
    with patch("graph.nodes.supervisor.LLMFactory.get_structured_llm") as mock_get_struct, \
         patch("core.db.db_client.fetch_tenant_documents", return_value=[]):
        mock_runnable = MagicMock()
        mock_runnable.ainvoke = AsyncMock(return_value=mock_supervisor_out)
        mock_get_struct.return_value = mock_runnable

        state = {
            "messages": [HumanMessage(content="What are Acme Corp's total assets and who is their auditor?")],
            "tenant_id": "default-tenant",
            "document_id": "doc-acme-10k",
            "required_modalities": []
        }
        
        sup_result = await supervisor_node(state)
        assert set(sup_result["required_modalities"]) == {"SQL", "VECTOR", "CYPHER"}
        
        state.update(sup_result)
        routes = supervisor_router(state)
        assert set(routes) == {"generate_sql", "generate_vector", "generate_cypher"}

    # 3. Test SQL Agent Node Execution
    mock_sql_plan = SQLPlanOutput(
        mode="exact",
        view_name="view_standardized_balance_sheet",
        filters_json=json.dumps({"company_name": "Acme Corp"}),
        reasoning="Fetch exact balance sheet row for Acme Corp"
    )
    
    mock_sql_llm_ans = MagicMock(content="Acme Corp has total assets of $5,000,000 and total liabilities of $2,000,000 for FY2025.")
    
    mock_sql_runnable = MagicMock()
    mock_sql_runnable.ainvoke = AsyncMock(return_value=mock_sql_plan)

    mock_llm_inst = MagicMock()
    mock_llm_inst.ainvoke = AsyncMock(return_value=mock_sql_llm_ans)

    with patch("graph.nodes.sql_agent.LLMFactory.get_structured_llm", return_value=mock_sql_runnable), \
         patch("graph.nodes.sql_agent.query_exact_rows") as mock_query_exact, \
         patch("graph.nodes.sql_agent.LLMFactory.get_llm", return_value=mock_llm_inst), \
         patch("core.db.db_client.fetch_tenant_documents", return_value=[]):
        
        mock_query_exact.invoke.return_value = json.dumps({"trust_level": "verified", "rows": mock_extracted_rows})
        
        gen_sql_res = await generate_sql_node(state)
        assert gen_sql_res["sql_query"] != ""
        
        state.update(gen_sql_res)
        exec_sql_res = execute_sql_node(state)
        assert "5000000" in exec_sql_res["sql_result"]
        assert len(exec_sql_res["references"]) >= 1

    # 4. Test Vector Agent Node Execution
    mock_vector_plan = VectorQueryOutput(search_query="Acme Corp 2025 SEC 10-K audit disclosure")
    mock_qdrant_response = json.dumps([
        {
            "document_id": "doc-acme-10k",
            "source_page": 12,
            "source_bbox": [50, 60, 200, 300],
            "text": "Acme Corp's chief executive officer signed the 2025 SEC 10-K audit disclosure."
        }
    ])
    mock_vector_ans = MagicMock(content="The 2025 audit disclosure was signed by Acme Corp's CEO.")

    with patch("graph.nodes.vector_agent.LLMFactory.get_structured_llm", return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_vector_plan))), \
         patch("graph.nodes.vector_agent.query_vector_db") as mock_qdrant, \
         patch("graph.nodes.vector_agent.LLMFactory.get_llm", return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_vector_ans))):
        
        mock_qdrant.ainvoke = AsyncMock(return_value=mock_qdrant_response)
        
        gen_vec_res = await generate_vector_node(state)
        assert gen_vec_res["vector_query"] != ""
        
        state.update(gen_vec_res)
        exec_vec_res = await execute_vector_node(state)
        assert "audit disclosure" in exec_vec_res["vector_result"].lower()
        assert len(exec_vec_res["references"]) == 1
        assert exec_vec_res["references"][0]["source_page"] == 12

    # 5. Test Cypher Graph Agent Node Execution
    mock_cypher_plan = CypherTemplateSelection(template_name="FIND_AUDITORS", entity_name="Acme Corp", reasoning="Find auditor")
    mock_graph_ans = MagicMock(content="Acme Corp is audited by Deloitte.")

    mock_fetch = MagicMock()
    mock_fetch.ainvoke = AsyncMock(return_value="Nodes: Entity")

    with patch("graph.nodes.cypher_agent.LLMFactory.get_structured_llm", return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_cypher_plan))), \
         patch("graph.nodes.cypher_agent.execute_cypher") as mock_cypher_exec, \
         patch("graph.nodes.cypher_agent.fetch_neo4j_schema", mock_fetch), \
         patch("graph.nodes.cypher_agent.LLMFactory.get_llm", return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_graph_ans))), \
         patch("core.db.db_client.fetch_tenant_documents", return_value=[]):
        
        mock_cypher_exec.ainvoke = AsyncMock(return_value=json.dumps([{"a.name": "DELOITTE"}]))
        
        gen_cypher_res = await generate_cypher_node(state)
        assert "MATCH" in gen_cypher_res["cypher_query"]
        
        state.update(gen_cypher_res)
        exec_cypher_res = await execute_cypher_node(state)
        assert "DELOITTE" in exec_cypher_res["cypher_result"]
