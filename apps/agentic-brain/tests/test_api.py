from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


@patch("api.routes.system.list_dead_letter_entries", new_callable=AsyncMock)
def test_dlq_endpoint(mock_list):
    mock_list.return_value = [{"status": "NEEDS_REVIEW", "document_id": "doc_1"}]
    response = client.get("/api/dlq?tenant_id=tenant1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["status"] == "NEEDS_REVIEW"
