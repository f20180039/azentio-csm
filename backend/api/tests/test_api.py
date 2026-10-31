import base64
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def auth_header(user: str = "analyst", pwd: str = "analyst") -> dict:
    cred = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


def test_health_endpoints():
    r1 = client.get("/health")
    assert r1.status_code == 200
    assert r1.json() == {"status": "ok", "service": "api"}

    r2 = client.get("/api/v1/health")
    assert r2.status_code == 200
    assert r2.json() == {"status": "ok", "service": "api"}


def test_auth_me():
    # Unauthenticated gives 401
    r_unauth = client.get("/api/v1/me")
    assert r_unauth.status_code == 401

    # Authenticated analyst gives 200
    r_auth = client.get("/api/v1/me", headers=auth_header("analyst", "analyst"))
    assert r_auth.status_code == 200
    data = r_auth.json()
    assert data["username"] == "analyst"
    assert "ANALYST" in data["roles"]


def test_support_calls_lifecycle():
    auth = auth_header("voice", "voice")

    # 1. Start support call
    r_start = client.post("/api/v1/support/calls", json={"channel": "VOICE"}, headers=auth)
    assert r_start.status_code == 201
    call_id = r_start.json()["id"]
    assert call_id is not None

    # 2. Add turns
    r_turn1 = client.post(
        f"/api/v1/support/calls/{call_id}/turns",
        json={"role": "customer", "text": "What is my EMI?", "at": "2026-10-31T06:00:00Z", "meta": {"intents": ["REPAYMENT"]}},
        headers=auth,
    )
    assert r_turn1.status_code == 201
    assert r_turn1.json()["seq"] == 1

    r_turn2 = client.post(
        f"/api/v1/support/calls/{call_id}/turns",
        json={"role": "agent", "text": "Your EMI is 12450.", "at": "2026-10-31T06:00:02Z", "meta": {"refs": ["SR-40102"]}},
        headers=auth,
    )
    assert r_turn2.status_code == 201
    assert r_turn2.json()["seq"] == 2

    # 3. Patch turn metadata
    r_patch = client.patch(
        f"/api/v1/support/calls/{call_id}/turns/1/meta",
        json={"verified": True, "intent_source": "rules"},
        headers=auth,
    )
    assert r_patch.status_code == 200

    # 4. End call
    r_end = client.post(
        f"/api/v1/support/calls/{call_id}/end",
        json={"outcome": "RESOLVED"},
        headers=auth,
    )
    assert r_end.status_code == 200

    # 5. Get call detail
    r_get = client.get(f"/api/v1/support/calls/{call_id}", headers=auth)
    assert r_get.status_code == 200
    call_detail = r_get.json()
    assert call_detail["id"] == call_id
    assert call_detail["channel"] == "VOICE"
    assert call_detail["outcome"] == "RESOLVED"
    assert call_detail["verified"] is True
    assert len(call_detail["turns"]) == 2
    assert call_detail["turns"][0]["meta"]["verified"] is True

    # 6. List calls
    r_list = client.get("/api/v1/support/calls?outcome=RESOLVED", headers=auth)
    assert r_list.status_code == 200
    items = r_list.json()["items"]
    assert any(c["id"] == call_id for c in items)


def test_renewals_queue_and_packs():
    auth = auth_header("analyst", "analyst")

    r_queue = client.get("/api/v1/renewals/queue", headers=auth)
    assert r_queue.status_code == 200
    # The queue is a bare list: frontend/src/api/renewals.ts and eval/simulate.py read it that way.
    assert len(r_queue.json()) > 0

    r_packs = client.get("/api/v1/packs", headers=auth)
    assert r_packs.status_code == 200
    assert len(r_packs.json()) > 0
