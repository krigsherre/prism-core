"""Keep alignment unit tests focused on pure helpers (no live LLM calls)."""
import json
import pytest
from unittest.mock import patch
from core.alignment import WaterfallAlignmentStrategy


@pytest.fixture
def strategy():
    return WaterfallAlignmentStrategy()


def test_update_schema(strategy):
    strategy.update_schema("new_table", {"col1": "str"})
    assert "new_table" in strategy.schema_registry
    assert strategy.schema_registry["new_table"] == {"col1": "str"}


def test_update_synonym(strategy):
    strategy.update_synonym("tenant1", "table1", "Label", "col1")
    assert strategy.synonym_cache[("tenant1", "table1", "Label")] == "col1"


def test_columnar_to_row_objects(strategy):
    rows = strategy._columnar_to_row_objects(
        {
            "Name": ["Acme", "Beta"],
            "Country": ["India", "US"],
        }
    )
    assert rows == [
        {"Name": "Acme", "Country": "India"},
        {"Name": "Beta", "Country": "US"},
    ]


def test_generate_context_chunks_from_json_rows(strategy):
    extracted = {
        "headers": ["A", "B"],
        "rows": [["1", "2"], ["3", "4"], ["5", "6"]],
    }
    with patch("core.alignment.settings") as mock_settings:
        mock_settings.chunk_size_rows = 2
        chunks = strategy._generate_context_chunks("", extracted)

    assert len(chunks) == 2
    first = json.loads(chunks[0]["target"])
    assert first == [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}]
    second = json.loads(chunks[1]["target"])
    assert second == [{"A": "5", "B": "6"}]
    assert chunks[1]["context"] is not None


def test_looks_financial(strategy):
    assert strategy._looks_financial("Consolidated Balance Sheet", "")
    assert not strategy._looks_financial("Employee handbook appendix", "")


def test_build_dynamic_schema_injects_context(strategy):
    columnar, model = strategy._build_dynamic_schema_model("standardized_balance_sheet", "vertical")
    assert "period_name" in columnar
    assert "context_currency" in columnar
    assert "total_assets" in columnar
    assert "data" in model.model_fields
