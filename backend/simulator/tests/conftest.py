import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.guard import get_now, get_store  # noqa: E402
from app.main import app  # noqa: E402
from app.store import BankStore  # noqa: E402

RAHUL = {"mobile": "9876500002", "dob": "1985-11-03", "ref": "CUST-1002"}
CUSTOMERS = {
    "CUST-1001": ("9876500001", "1990-04-12"),
    "CUST-1002": ("9876500002", "1985-11-03"),
    "CUST-1003": ("9876500003", "1992-07-21"),
    "CUST-1004": ("9876500004", "1978-02-14"),
    "CUST-1005": ("9876500005", "1988-09-30"),
    "CUST-1006": ("9876500006", "1995-12-05"),
}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path) -> BankStore:
    return BankStore(db_path=tmp_path / "sim.db")


@pytest.fixture
def client(store, clock):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_now] = lambda: clock.now
    yield TestClient(app)
    app.dependency_overrides.clear()


def verify(client, ref: str, dob: str | None = None, call_id: str | None = None, **extra):
    mobile, real_dob = CUSTOMERS[ref]
    body = {"mobile": mobile, "dob": dob or real_dob, "call_id": call_id or str(uuid.uuid4()), **extra}
    return client.post("/v1/verify", json=body)


def session_for(client, ref: str) -> dict:
    res = verify(client, ref)
    assert res.status_code == 200, res.text
    return {"X-Customer-Session": res.json()["session"]}
