import pytest
from core.hitl_review import generate_hitl_review, _heuristic_fallback


@pytest.mark.asyncio
async def test_generate_hitl_review_fallback_without_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # Force LLM failure path by breaking LLMFactory
    from core.llm_factory import LLMFactory
    monkeypatch.setattr(LLMFactory, "get_structured_llm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no llm")))

    review = await generate_hitl_review(
        target_table="subsidiaries",
        strict_columns=[{"name": "Acme", "country": "India"}],
        unmapped_jsonb=[{"share_pct": "100", "critic_error": "Logic Error: bad total"}],
        drifted_columns=["share_pct"],
        extracted_data={"Name": ["Acme"], "Country": ["India"]},
    )
    assert "summary" in review
    assert review["issues"]
    assert any("share_pct" in iss["column"] or "verification" in iss["column"] for iss in review["issues"])
    assert review["proposed_extracted_data"]


def test_heuristic_fallback_pinpoints_rows():
    review = _heuristic_fallback(
        "invoice",
        [{"total_amount": 10}],
        [{"extra_col": "x", "critic_error": "Sum mismatch"}],
        ["extra_col"],
        [],
        {"A": ["1"]},
    )
    assert review.issues
    assert "invoice" in review.summary.lower() or "HITL" in review.summary
