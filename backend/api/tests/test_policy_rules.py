"""Port of LapseRiskTest and PlaybookLoaderTest, plus persistence (env path, schema on start, idempotent seed)."""
from datetime import date

import pytest

from app.config import DEFAULT_PLAYBOOK, Settings
from app.db import Database
from app.lapse_risk import assess
from app.playbook import InvalidPlaybook, load_playbook
from app.vocab import Route

TODAY = date(2026, 10, 29)


def policy(expires="2026-11-03", last=15120, renewal=18450, **flags):
    return {"expires_on": expires, "last_premium": last, "renewal_premium": renewal, **flags}


def codes(r):
    return [s.code for s in r.signals]


def test_meera_scores_and_routes_to_agent():
    r = assess(policy(reminders_ignored=2), TODAY)
    assert codes(r) == ["EXPIRY_7D", "PREMIUM_UP_15", "REMINDERS_IGNORED"]
    assert r.score == 0.85 and r.route == Route.AGENT_CALL


def test_open_complaint_or_dnc_is_human_only():
    assert assess(policy(open_complaint=1), TODAY).route == Route.HUMAN_ONLY
    assert assess(policy(do_not_call=1), TODAY).route == Route.HUMAN_ONLY


def test_low_score_gets_reminder_sms():
    r = assess(policy("2026-11-19", 20000, 21800), TODAY)
    assert codes(r) == ["PREMIUM_UP_5"] and r.score == 0.15 and r.route == Route.REMINDER_SMS


def test_score_caps_at_one():
    r = assess(policy(claim_rejected_12m=1, autodebit_failed=1, reminders_ignored=5), TODAY)
    assert r.score == 1.0 and len(r.signals) == 5


def test_expiry_bands_are_inclusive():
    assert codes(assess(policy("2026-11-05", 100, 100), TODAY)) == ["EXPIRY_7D"]
    assert codes(assess(policy("2026-11-06", 100, 100), TODAY)) == ["EXPIRY_14D"]
    assert codes(assess(policy("2026-11-12", 100, 100), TODAY)) == ["EXPIRY_14D"]
    assert codes(assess(policy("2026-11-13", 100, 100), TODAY)) == []


def test_shipped_playbook_loads():
    pb = load_playbook(DEFAULT_PLAYBOOK)
    assert (pb.id, pb.max_discount_percent, pb.payment_plans) == ("health-renewal", 0, ("annual", "quarterly"))
    assert (pb.max_out_of_playbook_requests, pb.max_verify_failures, pb.removable_optional_addons) == (2, 3, True)


@pytest.mark.parametrize("body,message", [
    ("id: bad\nversion: 1\ngreeting: Hi\nmaxDiscountPercent: -1\npaymentPlans: [annual]\n"
     "removableOptionalAddons: true\nmaxOutOfPlaybookRequests: 2\nmaxVerifyFailures: 3\n", "must not be negative"),
    ("id: bad\nversion: 1\ngreeting: Hi\nmaxDiscountPercent: 101\npaymentPlans: [annual]\n"
     "removableOptionalAddons: true\nmaxOutOfPlaybookRequests: 2\nmaxVerifyFailures: 3\n", "at most 100"),
    ("id: bad\nversion: 1\ngreeting: Hi\nmaxDiscountPercent: 0\n"
     "removableOptionalAddons: true\nmaxOutOfPlaybookRequests: 2\nmaxVerifyFailures: 3\n", "paymentPlans is required"),
    ("id: bad\nversion: 1\ngreeting: Hi\nmaxDiscountPercent: 0\npaymentPlans: [annual]\nsurprise: 1\n"
     "removableOptionalAddons: true\nmaxOutOfPlaybookRequests: 2\nmaxVerifyFailures: 3\n", "unknown fields"),
])
def test_invalid_playbook_is_rejected(tmp_path, body, message):
    path = tmp_path / "pb.yml"
    path.write_text(body)
    with pytest.raises(InvalidPlaybook, match=message):
        load_playbook(path)


def test_db_path_comes_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "x" / "custom.db"))
    assert Settings.from_env().db_path == str(tmp_path / "x" / "custom.db")
    monkeypatch.delenv("API_DB_PATH")
    assert Settings.from_env().db_path.endswith("data/runtime/api.db")


def test_schema_created_on_start_and_seed_is_idempotent(tmp_path):
    path = tmp_path / "nested" / "api.db"
    db = Database(path)
    with db.read() as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        first = con.execute("SELECT count(*) FROM policies").fetchone()[0]
    assert {"policies", "cases", "calls", "audit_events"} <= tables
    assert first == 40
    with db.tx() as con:
        con.execute("UPDATE policies SET holder_name = 'Changed' WHERE id = 'HF-2291-0457'")
    db2 = Database(path)
    with db2.read() as con:
        assert con.execute("SELECT count(*) FROM policies").fetchone()[0] == 40
        assert con.execute("SELECT holder_name FROM policies WHERE id = 'HF-2291-0457'").fetchone()[0] == "Meera Iyer"
