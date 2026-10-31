"""Unit & Integration tests for Azentio-CSM Core API."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.security.pii import PIIRedactor
from app.security.audit import audit_ledger

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert "RBI-Outsourcing" in data["compliance"]


def test_pii_redactor():
    raw_prompt = "My Aadhaar is 2345 6789 0123, card is 4111 2222 3333 4102 and phone is +91-9876543210. Please help!"
    result = PIIRedactor.redact(raw_prompt)
    assert result.pii_detected is True
    assert "2345" not in result.redacted_text
    assert "[CARD_***_4102]" in result.redacted_text
    assert "[PHONE_***_3210]" in result.redacted_text


def test_auth_login():
    response = client.post("/api/v1/auth/login", json={"username": "analyst", "password": "analyst"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["role"] == "ANALYST"


def test_journey_card_block_and_audit():
    # 1. User says card stolen
    res1 = client.post("/api/v1/chat/message", json={
        "session_id": "test-session-001",
        "text": "My card got stolen, block it immediately!"
    })
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["intent"] == "CARD_BLOCK_INIT"
    assert "4102" in body1["response_text"]

    # 2. User selects card
    res2 = client.post("/api/v1/chat/message", json={
        "session_id": "test-session-001",
        "text": "Block the Platinum card 4102"
    })
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["step_up_needed"] is True
    assert "OTP" in body2["response_text"]

    # 3. User enters confirmation OTP
    res3 = client.post("/api/v1/chat/message", json={
        "session_id": "test-session-001",
        "text": "My OTP is 592810"
    })
    assert res3.status_code == 200
    body3 = res3.json()
    assert body3["intent"] == "CARD_BLOCK_CONFIRMED"
    assert "PERMANENTLY BLOCKED" in body3["response_text"]


def test_deterministic_prepayment_calculation():
    response = client.post("/api/v1/cbs/loans/prepay-calculate", json={
        "loan_id": "HL-901823",
        "prepayment_amount": 200000
    })
    assert response.status_code == 200
    data = response.json()
    assert data["prepayment_penalty"] == 0
    assert data["interest_saved"] > 0
    assert data["tenor_reduction_months"] > 0


def test_cryptographic_audit_ledger_integrity():
    is_valid, broken_idx = audit_ledger.verify_integrity()
    assert is_valid is True
    assert broken_idx is None

    # Verify audit endpoint
    res = client.get("/api/v1/audit/verify")
    assert res.status_code == 200
    assert res.json()["status"] == "VALID"
