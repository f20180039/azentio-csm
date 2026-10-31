"""Tests for FAQ search endpoint (Task C6)."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_faq_vehicle_loan_documents_first():
    """'what documents do I need for a vehicle loan' puts the vehicle-loan documents entry first."""
    resp = client.get("/v1/faq/search", params={"q": "what documents do I need for a vehicle loan"})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    items = data["items"]
    assert len(items) >= 1
    # First item must be vehicle loan documents (FAQ-003)
    assert items[0]["id"] == "FAQ-003"
    assert "vehicle loan" in items[0]["question"].lower()
    assert items[0]["score"] > 0
    assert isinstance(items[0]["score"], float)


def test_faq_stop_auto_debit_nach():
    """'how do I stop auto debit' matches the NACH entry."""
    resp = client.get("/v1/faq/search", params={"q": "how do I stop auto debit"})
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    assert len(items) >= 1
    # Must match FAQ-010 (How can I stop an EMI auto debit?) or FAQ-009 (NACH)
    assert items[0]["id"] in ("FAQ-010", "FAQ-009")
    assert "auto debit" in items[0]["question"].lower() or "nach" in items[0]["answer"].lower()
    assert items[0]["score"] > 0


def test_faq_unsupported_query_returns_empty():
    """'what's the weather today' returns items: []. This is the unsupported signal."""
    resp = client.get("/v1/faq/search", params={"q": "what's the weather today"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []

    # Also test another clearly unsupported query
    resp2 = client.get("/v1/faq/search", params={"q": "can you book me a flight to dubai"})
    assert resp2.status_code == 200
    assert resp2.json()["items"] == []


def test_faq_porter_stemming():
    """FTS5 with Porter stemming ensures 'prepay' matches 'prepayment'."""
    resp = client.get("/v1/faq/search", params={"q": "prepay"})
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    assert len(items) >= 1
    assert items[0]["id"] == "FAQ-011"
    assert "prepayment" in items[0]["question"].lower() or "prepayment" in items[0]["answer"].lower()


def test_faq_limit_parameter():
    """Check limit parameter restricts items returned."""
    resp = client.get("/v1/faq/search", params={"q": "loan", "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 2


def test_faq_empty_query():
    """Empty or whitespace query returns empty items list."""
    resp = client.get("/v1/faq/search", params={"q": "   "})
    assert resp.status_code == 200
    assert resp.json()["items"] == []
