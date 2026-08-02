import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consumers.dlq_consumer import DLQConsumer, _is_permanent_failure, _extract_critic_error
from core.config import settings


def _make_dlq_payload(document_id="doc-123", critic_error="Logic Error: math failed", **extra):
    payload = {
        "document_id": document_id,
        "tenant_id": "tenant-abc",
        "node_id": "node-1",
        "user_id": "user-1",
        "source_page": 2,
        "source_bbox": [0, 0, 100, 100],
        "target_table": "standardized_balance_sheet",
        "mapping_status": "FAILED_VERIFICATION",
        "strict_columns": [{"total_amount": 99.0}],
        "unmapped_jsonb": [{"critic_error": critic_error}],
        "extracted_data": {"total_amount": "99.0"},
        "markdown_content": "| Assets | 100 |",
        "parent_section_text": "Balance Sheet",
    }
    payload.update(extra)
    return payload


class TestDLQHelpers:
    def test_extract_critic_error(self):
        assert _extract_critic_error(_make_dlq_payload()) == "Logic Error: math failed"

    def test_permanent_when_flagged(self):
        p = _make_dlq_payload(failure_class="permanent")
        assert _is_permanent_failure(p, "whatever") is True

    def test_permanent_when_exhausted(self):
        p = _make_dlq_payload(reflexion_exhausted=True)
        assert _is_permanent_failure(p, "Logic Error: x") is True

    def test_retryable_logic_error(self):
        p = _make_dlq_payload()
        assert _is_permanent_failure(p, "Logic Error: total_assets") is False


class TestDLQConsumerLogic:
    @pytest.mark.asyncio
    async def test_reflexion_retry_routes_to_raw_table_doms(self):
        consumer = DLQConsumer()
        consumer._producer = AsyncMock()
        consumer._redis = AsyncMock()
        consumer._redis.get = AsyncMock(return_value=b"0")
        consumer._redis.incr = AsyncMock()
        consumer._redis.expire = AsyncMock()

        with patch("consumers.dlq_consumer.db_client") as mock_db:
            mock_conn = AsyncMock()
            mock_db.pool = MagicMock()
            mock_db.pool.acquire = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_db.connect = AsyncMock()

            await consumer._handle_payload(_make_dlq_payload())

        call_args = consumer._producer.send_and_wait.call_args
        assert call_args[0][0] == "raw_table_doms"
        sent = json.loads(call_args[1]["value"].decode("utf-8"))
        assert sent["reflexion_error"] == "Logic Error: math failed"
        assert sent["target_table"] == "standardized_balance_sheet"
        assert "extracted_data" in sent

    @pytest.mark.asyncio
    async def test_exhausted_goes_hitl(self):
        consumer = DLQConsumer()
        consumer._producer = AsyncMock()
        consumer._redis = AsyncMock()
        consumer._redis.hset = AsyncMock()
        consumer._redis.expire = AsyncMock()
        consumer._redis.set = AsyncMock()

        with patch("consumers.dlq_consumer.db_client") as mock_db, patch(
            "consumers.dlq_consumer.generate_hitl_review_from_dlq",
            new_callable=AsyncMock,
            return_value={"summary": "fix it", "issues": []},
        ):
            mock_conn = AsyncMock()
            mock_db.pool = MagicMock()
            mock_db.pool.acquire = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_db.connect = AsyncMock()

            await consumer._handle_payload(_make_dlq_payload(reflexion_exhausted=True))

        assert consumer._producer.send_and_wait.call_args[0][0] == "hitl_review"

    @pytest.mark.asyncio
    async def test_max_retries_goes_hitl(self):
        consumer = DLQConsumer()
        consumer._producer = AsyncMock()
        consumer._redis = AsyncMock()
        consumer._redis.get = AsyncMock(return_value=str(settings.max_retries).encode())
        consumer._redis.hset = AsyncMock()
        consumer._redis.expire = AsyncMock()
        consumer._redis.set = AsyncMock()

        with patch("consumers.dlq_consumer.db_client") as mock_db, patch(
            "consumers.dlq_consumer.generate_hitl_review_from_dlq",
            new_callable=AsyncMock,
            return_value={"summary": "needs human", "issues": []},
        ):
            mock_conn = AsyncMock()
            mock_db.pool = MagicMock()
            mock_db.pool.acquire = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_db.connect = AsyncMock()

            await consumer._handle_payload(_make_dlq_payload())

        assert consumer._producer.send_and_wait.call_args[0][0] == "hitl_review"
