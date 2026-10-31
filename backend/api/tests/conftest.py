import base64
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

# Module-level `app` (used by test_api.py) must not touch the real data/runtime database.
_TEST_DIR = tempfile.mkdtemp(prefix="api-test-")
os.environ["API_DB_PATH"] = os.path.join(_TEST_DIR, "api.db")
os.environ["PII_VAULT_PATH"] = os.path.join(_TEST_DIR, "pii_vault.db")

from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clock import Clock  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
MEERA = "HF-2291-0457"
MEERA_DOB = "1980-03-14"


def basic(user: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{user}".encode()).decode()}


ANALYST, REVIEWER, ADMIN, VOICE = basic("analyst"), basic("reviewer"), basic("admin"), basic("voice")


class MovableClock(Clock):
    def __init__(self, ist: str):
        super().__init__()
        self.set(ist)

    def set(self, ist: str) -> None:
        self._fixed = datetime.fromisoformat(ist).replace(tzinfo=IST)


@pytest.fixture
def make_client(tmp_path):
    made = []

    def make(ist: str = "2026-10-29T11:00:00", enforce: bool = True, db_name: str = "api.db", keyed: bool = True):
        clock = MovableClock(ist)
        # The PII vault key is generated in memory per test; keyed=False exercises the no-key path.
        settings = Settings(db_path=str(tmp_path / db_name), enforce_calling_hours=enforce,
                            pii_vault_path=str(tmp_path / "pii_vault.db"),
                            pii_vault_key=Fernet.generate_key().decode() if keyed else None)
        app = create_app(settings, clock)
        client = TestClient(app)
        client.clock = clock
        client.services = app.state.services
        made.append(client)
        return client

    yield make


@pytest.fixture
def client(make_client):
    return make_client()


def start_call(client, policy: str = MEERA, simulated: bool = False) -> str:
    r = client.post("/api/v1/renewals/calls", json={"policyId": policy, "simulated": simulated}, headers=ANALYST)
    assert r.status_code == 201, r.text
    return r.json()["callId"]


def verified_call(client, policy: str = MEERA) -> str:
    cid = start_call(client, policy)
    r = client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": MEERA_DOB}, headers=VOICE)
    assert r.json()["verified"] is True
    return cid


def actions(client, cid: str) -> list[str]:
    return [e["action"] for e in client.get(f"/api/v1/cases/{cid}/audit", headers=ANALYST).json()]


def audit(client, cid: str) -> list[dict]:
    return client.get(f"/api/v1/cases/{cid}/audit", headers=ANALYST).json()
