import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
from kafka.consumers.auto_promote import AutoPromoteConsumer

@pytest.fixture
def mock_sql_repo():
    return AsyncMock()

@pytest.fixture
def mock_qdrant_repo():
    return AsyncMock()

@pytest.mark.asyncio
async def test_auto_promote_consumer_run(mock_sql_repo):
    consumer_app = AutoPromoteConsumer(mock_sql_repo)
    
    payload = {
        "payload": {
            "op": "c",
            "after": {
                "target_table": "my_table"
            }
        }
    }
    
    class MockConsumer:
        def __init__(self, *args, **kwargs):
            pass
        async def start(self): pass
        async def stop(self): pass
        def __aiter__(self):
            class Msg:
                value = json.dumps(payload).encode("utf-8")
                key = b"tenant-1"
                headers = []
            async def _gen():
                yield Msg()
                raise asyncio.CancelledError()
            return _gen()
    class MockProducer:
        def __init__(self, *args, **kwargs):
            pass
        async def start(self): pass
        async def stop(self): pass
        async def send_and_wait(self, *args, **kwargs): pass
            
    with patch("kafka.consumers.auto_promote.AIOKafkaConsumer", MockConsumer), \
         patch("kafka.consumers.auto_promote.AIOKafkaProducer", MockProducer):
        await consumer_app.run()
        
    mock_sql_repo.get_unmapped_rows_by_table.assert_called_once_with("my_table")
