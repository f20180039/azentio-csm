from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "bank-simulator"}


def test_chat_message_is_404():
    res = client.get("/api/v1/chat/message")
    assert res.status_code == 404
