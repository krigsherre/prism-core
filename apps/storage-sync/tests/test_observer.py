import sys
from unittest.mock import MagicMock
sys.modules['aiokafka'] = MagicMock()
import asyncio
import pytest
import json
from unittest.mock import AsyncMock, patch
from kafka.cdc.observer import DebeziumObserver

@pytest.fixture
def mock_qdrant_repo():
    return AsyncMock()

@pytest.fixture
def mock_embeddings():
    mock = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_debezium_observer_insert(mock_qdrant_repo, mock_embeddings):
    observer = DebeziumObserver(mock_qdrant_repo)
    observer._real_embedding = AsyncMock(return_value=[0.1] * 1536)
    
    class MockConsumer:
        def __init__(self, *args, **kwargs): pass
        async def start(self): pass
        async def stop(self): pass
        def __aiter__(self):
            class Msg:
                value = json.dumps({
                    "payload": {
                        "op": "c",
                        "after": {
                            "node_id": "node-1",
                            "document_id": "doc-1",
                            "content": "Updated Table Data",
                            "source_page": 1,
                            "source_bbox": [0,0,10,10]
                        }
                    }
                }).encode("utf-8")
            async def _gen():
                yield Msg()
                raise asyncio.CancelledError()
            return _gen()
            
    with patch("kafka.cdc.observer.AIOKafkaConsumer", MockConsumer):
        await observer.run()
        
    mock_qdrant_repo.upsert_vector.assert_called_once()
    observer._real_embedding.assert_called_once_with("Updated Table Data")


@pytest.mark.asyncio
async def test_debezium_observer_delete(mock_qdrant_repo, mock_embeddings):
    observer = DebeziumObserver(mock_qdrant_repo)
    observer._real_embedding = AsyncMock(return_value=[0.1] * 1536)
    
    class MockConsumer:
        def __init__(self, *args, **kwargs): pass
        async def start(self): pass
        async def stop(self): pass
        def __aiter__(self):
            class Msg:
                value = json.dumps({
                    "payload": {
                        "op": "d",
                        "before": {
                            "node_id": "node-2"
                        }
                    }
                }).encode("utf-8")
            async def _gen():
                yield Msg()
                raise asyncio.CancelledError()
            return _gen()
            
    with patch("kafka.cdc.observer.AIOKafkaConsumer", MockConsumer):
        await observer.run()
        
    mock_qdrant_repo.delete_vector.assert_called_once_with("node-2")
    observer._real_embedding.assert_not_called()
