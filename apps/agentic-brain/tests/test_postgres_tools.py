import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.postgres_tools import (
    get_allowed_views,
    is_allowed_view,
    list_exact_views,
    query_exact_rows,
    select_by_mapping_priority,
    _parse_filters,
    SYSTEM_COLUMNS,
)
from graph.nodes.sql_agent import _parse_plan, _build_references_from_exact


def test_allowed_views_from_registry():
    views = get_allowed_views()
    assert "view_invoice_line_items" in views
    assert "quantity" in views["view_invoice_line_items"]
    assert is_allowed_view("view_invoice_line_items")
    assert not is_allowed_view("extracted_tables")
    assert not is_allowed_view("view_;drop table")


def test_list_exact_views_mentions_views():
    text = list_exact_views.invoke({})
    assert "view_invoice_line_items" in text
    assert "tenant_id" in text or "system:" in text
    assert "MAPPED" in text


def test_select_by_mapping_priority_prefers_mapped():
    rows = [
        {"id": "1", "mapping_status": "NEEDS_REVIEW", "total_assets": 1},
        {"id": "2", "mapping_status": "MAPPED", "total_assets": 99},
        {"id": "3", "mapping_status": "NEEDS_REVIEW", "total_assets": 2},
    ]
    selected, trust = select_by_mapping_priority(rows)
    assert trust == "verified"
    assert len(selected) == 1
    assert selected[0]["id"] == "2"
    assert selected[0]["trust_level"] == "verified"


def test_select_by_mapping_priority_falls_back_to_review():
    rows = [
        {"id": "1", "mapping_status": "NEEDS_REVIEW", "total_assets": 1},
        {"id": "2", "mapping_status": "FAILED", "total_assets": 0},
    ]
    selected, trust = select_by_mapping_priority(rows)
    assert trust == "provisional"
    assert len(selected) == 1
    assert selected[0]["id"] == "1"
    assert selected[0]["trust_level"] == "provisional"


def test_select_by_mapping_priority_empty():
    selected, trust = select_by_mapping_priority([])
    assert selected == []
    assert trust == "empty"


def test_parse_filters_rejects_unknown_column():
    with pytest.raises(ValueError, match="not allowed"):
        _parse_filters('{"evil":"x"}', set(SYSTEM_COLUMNS) | {"vendor_name"})


def test_parse_filters_ok():
    out = _parse_filters('{"vendor_name":"Acme"}', set(SYSTEM_COLUMNS) | {"vendor_name"})
    assert out == {"vendor_name": "Acme"}


def test_query_exact_rows_rejects_non_allowlisted_view():
    result = query_exact_rows.invoke(
        {
            "view_name": "secret_table",
            "tenant_id": "t1",
            "document_id": "d1",
            "filters_json": "{}",
            "limit": 10,
        }
    )
    # Non-allowlisted names fall back to extracted_tables (or error if DB unavailable).
    assert "SQL Error" in result or "extracted_tables" in result


@patch("tools.postgres_tools._run_async")
def test_query_exact_rows_success(mock_run):
    def _consume(coro):
        # Prevent "coroutine was never awaited" when _run_async is mocked
        if hasattr(coro, "close"):
            coro.close()
        return [
            {
                "id": "1",
                "tenant_id": "t1",
                "sys_document_id": "d1",
                "sys_node_id": "n1",
                "source_page": 2,
                "quantity": 5,
                "mapping_status": "MAPPED",
            }
        ]

    mock_run.side_effect = _consume
    result = query_exact_rows.invoke(
        {
            "view_name": "view_invoice_line_items",
            "tenant_id": "t1",
            "document_id": "d1",
            "filters_json": "{}",
            "limit": 10,
        }
    )
    data = json.loads(result)
    assert data["row_count"] == 1
    assert data["rows"][0]["quantity"] == 5
    assert data["data_quality"] == "verified"
    assert data["rows"][0]["trust_level"] == "verified"
    mock_run.assert_called_once()


@patch("tools.postgres_tools._run_async")
def test_query_exact_rows_prefers_mapped_over_review(mock_run):
    def _consume(coro):
        if hasattr(coro, "close"):
            coro.close()
        return [
            {
                "id": "review",
                "tenant_id": "t1",
                "sys_document_id": "d1",
                "quantity": 1,
                "mapping_status": "NEEDS_REVIEW",
            },
            {
                "id": "mapped",
                "tenant_id": "t1",
                "sys_document_id": "d1",
                "quantity": 9,
                "mapping_status": "MAPPED",
            },
        ]

    mock_run.side_effect = _consume
    result = query_exact_rows.invoke(
        {
            "view_name": "view_invoice_line_items",
            "tenant_id": "t1",
            "document_id": "d1",
            "filters_json": "{}",
            "limit": 10,
        }
    )
    data = json.loads(result)
    assert data["data_quality"] == "verified"
    assert data["row_count"] == 1
    assert data["rows"][0]["id"] == "mapped"


@patch("tools.postgres_tools._run_async")
def test_query_exact_rows_provisional_fallback(mock_run):
    def _consume(coro):
        if hasattr(coro, "close"):
            coro.close()
        return [
            {
                "id": "review",
                "tenant_id": "t1",
                "sys_document_id": "d1",
                "quantity": 3,
                "mapping_status": "NEEDS_REVIEW",
            },
        ]

    mock_run.side_effect = _consume
    result = query_exact_rows.invoke(
        {
            "view_name": "view_invoice_line_items",
            "tenant_id": "t1",
            "document_id": "d1",
            "filters_json": "{}",
            "limit": 10,
        }
    )
    data = json.loads(result)
    assert data["data_quality"] == "provisional"
    assert "provisional" in data.get("quality_note", "").lower()
    assert data["row_count"] == 1


def test_parse_plan_json_and_legacy_sql():
    plan = _parse_plan(json.dumps({"mode": "exact", "view_name": "view_invoice_line_items"}))
    assert plan["mode"] == "exact"
    legacy = _parse_plan("SELECT measure FROM invoices")
    assert legacy["mode"] == "cube"
    assert "SELECT" in legacy["sql"]


def test_build_references_from_exact():
    payload = json.dumps(
        {
            "view": "view_invoice_line_items",
            "rows": [
                {"sys_document_id": "d1", "sys_node_id": "n1", "source_page": 3},
            ],
        }
    )
    refs = _build_references_from_exact(payload)
    assert len(refs) == 1
    assert refs[0]["document_id"] == "d1"
    assert refs[0]["page"] == 3
    assert refs[0]["source"] == "postgres_exact"


def test_inject_tenant_id_uses_tenant_id_column():
    from tools.cube_tools import inject_tenant_id_sql

    secured = inject_tenant_id_sql("SELECT * FROM invoices", "tenant-abc")
    assert "tenant_id" in secured
    assert "sys_tenant_id" not in secured
    assert "tenant-abc" in secured
