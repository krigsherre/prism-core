import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from repositories.qdrant_repo import QdrantRepository

@pytest.fixture
def mock_qdrant_client():
    client = MagicMock()
    client.upsert = AsyncMock()
    client.delete = AsyncMock()
    client.get_collection = AsyncMock()
    client.create_collection = AsyncMock()
    
    with patch('repositories.qdrant_repo.AsyncQdrantClient', return_value=client):
        yield client

@pytest.mark.asyncio
async def test_qdrant_upsert_vector(mock_qdrant_client):
    repo = QdrantRepository()
    
    await repo.upsert_vector(
        node_id="test-node-123",
        document_id="test-doc",
        vector=[0.1] * 384,
        payload={"key": "value"}
    )
    
    assert mock_qdrant_client.upsert.called
    args, kwargs = mock_qdrant_client.upsert.call_args
    assert kwargs["collection_name"] == "document_chunks"
    
@pytest.mark.asyncio
async def test_qdrant_delete_vector(mock_qdrant_client):
    repo = QdrantRepository()
    
    await repo.delete_vector("test-node-123")
    
    assert mock_qdrant_client.delete.called
    args, kwargs = mock_qdrant_client.delete.call_args
    assert kwargs["collection_name"] == "document_chunks"
