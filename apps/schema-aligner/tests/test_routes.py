import pytest
from fastapi.testclient import TestClient
from api.routes import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_readyz(mocker):
    mocker.patch("api.routes.AIOKafkaClient.bootstrap", return_value=None)
    mocker.patch("api.routes.AIOKafkaClient.close", return_value=None)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
