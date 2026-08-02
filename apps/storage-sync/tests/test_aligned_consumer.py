import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
from kafka.consumers.aligned_consumer import AlignedSQLConsumer

@pytest.fixture
def mock_sql_repo():
    return AsyncMock()

@pytest.fixture
def mock_qdrant_repo():
    return AsyncMock()

@pytest.mark.asyncio
async def test_aligned_consumer_run(mock_sql_repo, mock_qdrant_repo):
    consumer_app = AlignedSQLConsumer(mock_sql_repo)
    
    payload = {
        "tenant_id": "tenant-1",
        "document_id": "doc-1",
        "node_id": "node-1",
        "target_table": "my_table",
        "mapping_status": "SUCCESS",
        "strict_columns": [{"col1": "val1"}],
        "unmapped_jsonb": [{}],
        "source_page": 1,
        "source_bbox": [0,0,10,10],
        "user_id": "user-1"
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
            
    with patch("kafka.consumers.aligned_consumer.AIOKafkaConsumer", MockConsumer), \
         patch("kafka.consumers.aligned_consumer.AIOKafkaProducer", MockProducer):
        await consumer_app.run()
        
    mock_sql_repo.insert_aligned_rows.assert_called_once()
