import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from graph.nodes.sql_agent import _is_aggregation_intent, _parse_plan
from core.config import settings


def test_is_aggregation_intent():
    assert _is_aggregation_intent("What is the total revenue?")
    assert _is_aggregation_intent("How many invoices were late?")
    assert not _is_aggregation_intent("What is the share capital for Infosys BPM?")
    assert not _is_aggregation_intent("Show me row 2 country")


def test_config_has_no_hardcoded_anthropic_secret():
    assert not str(settings.anthropic_api_key or "").startswith("sk-ant-api03-")


@pytest.mark.asyncio
async def test_claim_next_task_returns_none_when_empty():
    from consumers.work_queue_worker import claim_next_task

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=acquire_cm)

    with patch("consumers.work_queue_worker.db_client") as mock_db:
        mock_db.pool = mock_pool
        mock_db.connect = AsyncMock()
        result = await claim_next_task("worker-1")
        assert result is None


@pytest.mark.asyncio
async def test_execute_claimed_task_fails_without_prompt():
    from consumers.work_queue_worker import execute_claimed_task

    with patch("consumers.work_queue_worker.fail_task", new_callable=AsyncMock) as mock_fail:
        await execute_claimed_task(
            {
                "id": "t1",
                "tenant_id": "tenant",
                "document_id": None,
                "prompt": "",
                "system_prompt": "be helpful",
            }
        )
        mock_fail.assert_awaited_once()
        assert "missing prompt" in mock_fail.await_args.args[1].lower()


def test_parse_plan_exact():
    plan = _parse_plan(
        json.dumps({"mode": "exact", "view_name": "view_invoice_line_items", "filters_json": "{}"})
    )
    assert plan["mode"] == "exact"
