"""Port of SupportControllerTest and SupportServiceTest."""
import uuid

import pytest

from conftest import ADMIN, ANALYST, REVIEWER, VOICE, audit, start_call
from app.errors import ApiError
from app.services.support import parse
from app.vocab import Channel, Outcome, TurnRole

BASE = "/api/v1/support/calls"


def start(client, channel="SIM_AUDIO") -> str:
    r = client.post(BASE, json={"channel": channel}, headers=VOICE)
    assert r.status_code == 201 and r.json()["id"]
    return r.json()["id"]


def turn(client, cid, role, text, meta=None, at="2026-10-31T06:00:01Z"):
    body = {"role": role, "text": text, "at": at}
    if meta is not None:
        body["meta"] = meta
    return client.post(f"{BASE}/{cid}/turns", json=body, headers=VOICE)


def end(client, cid, outcome):
    return client.post(f"{BASE}/{cid}/end", json={"outcome": outcome}, headers=VOICE)


def test_full_round_trip_with_merged_meta_and_listing(make_client):
    client = make_client("2026-10-31T11:30:00")
    cid = start(client)
    r = turn(client, cid, "customer", "When is my EMI due?", {"intents": ["REPAYMENT"], "verified": True})
    assert r.status_code == 201 and r.json() == {"seq": 1}
    r = turn(client, cid, "agent", "Your next EMI is due on the 5th.", {
        "tool_trace": [{"name": "get_loan", "args": {"loan_id": "LN-1"}, "result_summary": "next_due 2026-11-05"}],
        "retrieved": {"get_loan": {"next_due": "2026-11-05"}}, "refs": []}, at="2026-10-31T06:00:03Z")
    assert r.json() == {"seq": 2}
    p = client.patch(f"{BASE}/{cid}/turns/1/meta", json={"intent_source": "llm"}, headers=VOICE)
    assert p.status_code == 200
    assert p.json()["meta"] == {"intents": ["REPAYMENT"], "verified": True, "intent_source": "llm"}
    assert end(client, cid, "TICKET_CREATED").status_code == 200

    d = client.get(f"{BASE}/{cid}", headers=ANALYST).json()
    assert d["id"] == cid and d["channel"] == "SIM_AUDIO"
    assert d["startedAt"] == "2026-10-31T06:00:00Z" and d["endedAt"] == "2026-10-31T06:00:00Z"
    assert d["outcome"] == "TICKET_CREATED" and d["verified"] is True
    assert [t["seq"] for t in d["turns"]] == [1, 2]
    assert d["turns"][0]["role"] == "customer" and d["turns"][0]["at"] == "2026-10-31T06:00:01Z"
    assert d["turns"][0]["meta"]["intent_source"] == "llm"
    assert d["turns"][1]["meta"]["tool_trace"][0]["result_summary"] == "next_due 2026-11-05"
    assert d["turns"][1]["meta"]["retrieved"]["get_loan"]["next_due"] == "2026-11-05"

    items = client.get(BASE, params={"outcome": "TICKET_CREATED", "limit": 50}, headers=REVIEWER).json()["items"]
    assert items == [{"id": cid, "channel": "SIM_AUDIO", "startedAt": d["startedAt"], "endedAt": d["endedAt"],
                      "outcome": "TICKET_CREATED", "verified": True, "turnCount": 2, "intents": ["REPAYMENT"],
                      "rating": None}]
    assert client.get(BASE, params={"outcome": "RESOLVED"}, headers=ADMIN).json()["items"] == []

    events = audit(client, cid)
    assert [e["action"] for e in events] == ["call.started", "call.ended"]
    assert events[0]["actor"] == "voice"
    assert events[1]["payload"] == {"outcome": "TICKET_CREATED", "turnCount": 2}


def test_unknown_outcome_is_400_and_call_stays_open(client):
    cid = start(client)
    r = end(client, cid, "HANDED_OFF")
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["detail"].startswith("outcome must be one of RESOLVED")
    assert "HANDED_OFF" in r.json()["detail"]
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["endedAt"] is None
    assert client.get(BASE, params={"outcome": "NOPE"}, headers=ANALYST).status_code == 400


def test_unknown_channel_and_role_are_400(client):
    r = client.post(BASE, json={"channel": "FAX"}, headers=VOICE)
    assert r.status_code == 400 and r.json()["detail"].startswith("channel must be one of VOICE, SIM_AUDIO, TEXT")
    assert client.post(BASE, json={}, headers=VOICE).status_code == 400
    cid = start(client)
    r = turn(client, cid, "bot", "hi")
    assert r.status_code == 400 and r.json()["detail"].startswith("role must be one of customer, agent")
    assert turn(client, cid, "Customer", "hi").status_code == 400


def test_ending_twice_is_409_and_keeps_first_outcome(client):
    cid = start(client)
    assert end(client, cid, "RESOLVED").status_code == 200
    r = end(client, cid, "ESCALATED")
    assert r.status_code == 409 and r.json()["detail"] == "CALL_ALREADY_ENDED"
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["outcome"] == "RESOLVED"


def test_turn_after_end_is_409_but_meta_patch_still_works(client):
    cid = start(client)
    turn(client, cid, "customer", "I want to complain")
    assert end(client, cid, "ESCALATED").status_code == 200
    case = client.get(f"/api/v1/cases/{cid}", headers=ANALYST).json()
    assert case["status"] == "ESCALATED" and case["caseType"] == "support_call"
    r = turn(client, cid, "agent", "late")
    assert r.status_code == 409 and r.json()["detail"] == "CALL_ENDED"
    p = client.patch(f"{BASE}/{cid}/turns/1/meta", json={"intents": ["COMPLAINT"]}, headers=VOICE)
    assert p.status_code == 200
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["turns"][0]["meta"]["intents"] == ["COMPLAINT"]


def test_patch_on_missing_turn_is_404(client):
    cid = start(client)
    r = client.patch(f"{BASE}/{cid}/turns/1/meta", json={"intents": ["KYC"]}, headers=VOICE)
    assert r.status_code == 404
    assert client.patch(f"{BASE}/{cid}/turns/1/meta", json=["x"], headers=VOICE).status_code == 400


def test_turns_keep_order_and_summary_derives_from_customer_turns(client):
    cid = start(client, "TEXT")
    turn(client, cid, "customer", "EMI date?", {"intents": ["REPAYMENT"], "verified": True}, at=None)
    turn(client, cid, "agent", "The 5th.", {"tool_trace": [{"name": "get_loan"}], "intents": ["IGNORED_ON_AGENT"]})
    turn(client, cid, "customer", "And my card?", {"intents": ["CARD_BLOCK", "REPAYMENT"]})
    turn(client, cid, "customer", "Thanks")
    client.patch(f"{BASE}/{cid}/turns/1/meta", json={"intent_source": "rules", "verified": True}, headers=VOICE)
    client.patch(f"{BASE}/{cid}/turns/1/meta", json={"intent_source": "llm"}, headers=VOICE)
    d = client.get(f"{BASE}/{cid}", headers=VOICE).json()
    assert [t["seq"] for t in d["turns"]] == [1, 2, 3, 4]
    assert d["turns"][0]["meta"]["intent_source"] == "llm"
    assert d["turns"][0]["at"] == "2026-10-29T05:30:00Z"  # filled from the clock when absent
    assert d["turns"][3]["meta"] == {}
    item = client.get(BASE, headers=ANALYST).json()["items"][0]
    assert item["intents"] == ["REPAYMENT", "CARD_BLOCK"] and item["turnCount"] == 4


def test_verified_only_counts_customer_turns(client):
    cid = start(client, "TEXT")
    turn(client, cid, "agent", "Verified you.", {"verified": True})
    turn(client, cid, "customer", "ok", {"verified": False})
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["verified"] is False


def test_list_is_newest_first_and_limit_is_bounded(client):
    first = start(client)
    client.clock.set("2026-10-29T11:05:00")
    second = start(client)
    ids = [i["id"] for i in client.get(BASE, headers=ANALYST).json()["items"]]
    assert ids == [second, first]
    assert client.get(BASE, params={"limit": 0}, headers=ANALYST).status_code == 400
    assert client.get(BASE, params={"limit": 201}, headers=ANALYST).status_code == 400


def test_renewal_call_is_not_a_support_call(client):
    rid = start_call(client)
    assert client.get(f"{BASE}/{rid}", headers=ANALYST).status_code == 404
    assert client.get(BASE, headers=ANALYST).json()["items"] == []
    assert client.get(f"{BASE}/{uuid.uuid4()}", headers=ANALYST).status_code == 404


def test_vocabularies_reject_unknown_values():
    with pytest.raises(ApiError) as e:
        parse(Outcome, "outcome", "HANDED_OFF")
    assert e.value.status == 400 and "RESOLVED" in e.value.detail and "HANDED_OFF" in e.value.detail
    with pytest.raises(ApiError):
        parse(Channel, "channel", None)
    with pytest.raises(ApiError):
        parse(TurnRole, "role", "Customer")
    assert parse(Outcome, "outcome", "ROUTED") is Outcome.ROUTED


def test_a_phone_call_starts_and_is_listed_with_its_channel(client):
    cid = start(client, "PHONE")
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["channel"] == "PHONE"
    assert [c["channel"] for c in client.get(BASE, headers=ANALYST).json()["items"]] == ["PHONE"]


def test_unknown_channels_are_still_400_and_list_phone(client):
    r = client.post(BASE, json={"channel": "SMS"}, headers=VOICE)
    assert r.status_code == 400 and r.json()["detail"].startswith("channel must be one of VOICE, SIM_AUDIO, TEXT, PHONE")


def test_a_database_made_before_phone_keeps_its_calls_and_accepts_phone(make_client, tmp_path):
    import sqlite3

    old_cid = start(make_client(db_name="old.db"), "TEXT")
    con = sqlite3.connect(tmp_path / "old.db")  # put back the CHECK a database created before PHONE has
    con.execute("PRAGMA writable_schema = ON")
    con.execute("UPDATE sqlite_master SET sql = replace(sql, ', ''PHONE''', '') WHERE name = 'calls'")
    con.commit()
    con.close()
    con = sqlite3.connect(tmp_path / "old.db")
    assert "'PHONE'" not in con.execute("SELECT sql FROM sqlite_master WHERE name = 'calls'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE calls SET channel = 'PHONE' WHERE id = ?", (old_cid,))
    con.close()

    client = make_client(db_name="old.db")
    cid = start(client, "PHONE")
    channels = {c["id"]: c["channel"] for c in client.get(BASE, headers=ANALYST).json()["items"]}
    assert channels == {old_cid: "TEXT", cid: "PHONE"}
