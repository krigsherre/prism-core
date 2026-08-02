import json
import pytest
from unittest.mock import AsyncMock

from consumers.redis_watcher import RedisKeyspaceListener

class TestRedisWatcherLogic:
    """Test the Redis Keyspace Listener's timeout handling."""

    @pytest.mark.asyncio
    async def test_handle_timeout_routes_to_permanent_failure(self):
        watcher = RedisKeyspaceListener()
        watcher._redis = AsyncMock()
        watcher._producer = AsyncMock()

        original_payload = json.dumps({"document_id": "doc-expired", "data": "test"})
        watcher._redis.hget = AsyncMock(return_value=original_payload.encode("utf-8"))
        watcher._redis.delete = AsyncMock()

        await watcher._handle_timeout("doc-expired")

        watcher._producer.send_and_wait.assert_called_once_with(
            "permanent_failure",
            key=b"doc-expired",
            value=original_payload.encode("utf-8"),
        )
        watcher._redis.delete.assert_called_once_with("hitl:payload:doc-expired")

    @pytest.mark.asyncio
    async def test_handle_timeout_no_payload_does_not_crash(self):
        watcher = RedisKeyspaceListener()
        watcher._redis = AsyncMock()
        watcher._producer = AsyncMock()
        watcher._redis.hget = AsyncMock(return_value=None)

        await watcher._handle_timeout("doc-missing")
        watcher._producer.send_and_wait.assert_not_called()
