import pytest
from core.employee_personas import list_personas, get_persona
from graph.nodes.employee_critic import employee_critic_node


def test_list_employee_personas():
    """Verify employee persona listing contains required enterprise roles."""
    personas = list_personas()
    assert len(personas) >= 4

    roles = {p["id"] for p in personas}
    assert "forensic_auditor" in roles
    assert "compliance_officer" in roles
    assert "credit_analyst" in roles
    assert "research_assistant" in roles


def test_get_persona():
    """Verify fallback and exact persona lookup."""
    auditor = get_persona("forensic_auditor")
    assert auditor["name"] == "Forensic Accounting Auditor"

    fallback = get_persona("non_existent_role")
    assert fallback["id"] == "research_assistant"


@pytest.mark.asyncio
async def test_employee_critic_node():
    """Verify audit critic attaches persona verification header."""
    state = {
        "final_answer": "Revenue grew by 15% year-over-year.",
        "target_task": "forensic_auditor"
    }
    result = await employee_critic_node(state)
    assert "Senior Forensic Accounting Auditor Audit Verification" in result["final_answer"]
    assert "Revenue grew by 15%" in result["final_answer"]
