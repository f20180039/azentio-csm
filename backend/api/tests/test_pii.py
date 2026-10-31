"""Transcript PII redaction: tokens in the calls DB, values only in the separate encrypted vault (Task P1)."""
import json
import logging
import sqlite3
from datetime import date

import pytest
from cryptography.fernet import Fernet

from conftest import ADMIN, ANALYST, REVIEWER, VOICE, audit
from app.pii import Redactor, redact_text
from app.pii_vault import PiiVault
from app.vocab import AuditAction, PiiKind
from scripts.redact_existing import redact_all

BASE = "/api/v1/support/calls"
TODAY = date(2026, 10, 29)  # the conftest clock's date
MOBILE, DOB_ISO, NAME = "9876500002", "1985-11-03", "Rahul"
SPOKEN = f"My number is 98765 00002 and I was born on 3rd November 1985"
META = {
    "tool_trace": [{"name": "verify_customer", "args": {"mobile": MOBILE, "date_of_birth": DOB_ISO},
                    "result": "verified"}],
    "retrieved": {"verify_customer": {"customer": {"first_name": NAME, "customer_ref": "CUST-1002"}}},
    "refs": ["SR-40102"], "verified": True,
}


def start(client) -> str:
    r = client.post(BASE, json={"channel": "SIM_AUDIO"}, headers=VOICE)
    assert r.status_code == 201
    return r.json()["id"]


def turn(client, cid, role, text, meta=None):
    body = {"role": role, "text": text, "at": "2026-10-31T06:00:01Z"}
    if meta is not None:
        body["meta"] = meta
    r = client.post(f"{BASE}/{cid}/turns", json=body, headers=VOICE)
    assert r.status_code == 201, r.text
    return r.json()["seq"]


def stored_transcript(client, cid) -> str:
    with client.services.db.read() as con:
        return con.execute("SELECT transcript FROM calls WHERE id = ?", (cid,)).fetchone()["transcript"]


def stored_correction(client, cid, seq) -> str:
    with client.services.db.read() as con:
        return con.execute("SELECT correction FROM turn_feedback WHERE call_id = ? AND seq = ?",
                           (cid, seq)).fetchone()["correction"]


def pii_call(client) -> str:
    cid = start(client)
    turn(client, cid, "customer", SPOKEN, META)
    return cid


def test_turn_text_and_meta_are_stored_redacted(client):
    cid = pii_call(client)
    raw = stored_transcript(client, cid)
    for token in ("[MOBILE#1]", "[DOB#1]", "[NAME#1]"):
        assert token in raw
    for leak in ("98765", MOBILE, "1985", NAME):
        assert leak not in raw
    turns = json.loads(raw)
    meta = turns[0]["meta"]
    assert turns[0]["text"] == "My number is [MOBILE#1] and I was born on [DOB#1]"
    assert meta["tool_trace"][0]["args"] == {"mobile": "[MOBILE#1]", "date_of_birth": "[DOB#1]"}
    assert meta["tool_trace"][0]["name"] == "verify_customer"  # the tool name is not a person's name
    assert meta["retrieved"]["verify_customer"]["customer"] == {"first_name": "[NAME#1]", "customer_ref": "CUST-1002"}
    assert meta["refs"] == ["SR-40102"] and meta["verified"] is True
    # Every API response other than the reveal route holds only tokens.
    shown = client.get(f"{BASE}/{cid}", headers=ANALYST).json()["turns"][0]
    assert shown["text"] == "My number is [MOBILE#1] and I was born on [DOB#1]"
    assert shown["meta"]["tool_trace"][0]["args"]["mobile"] == "[MOBILE#1]"


@pytest.mark.parametrize("text, expected", [
    ("+91 98765-00002", "[MOBILE#1]"),
    ("nine eight seven six five zero zero zero zero two", "[DIGITS#1]"),
    ("1234 5678 9012", "[AADHAAR#1]"),
    ("ABCDE1234F", "[PAN#1]"),
    ("4111 1111 1111 1111", "[CARD#1]"),
    ("rahul.s@example.com", "[EMAIL#1]"),
    ("123456789012345", "[ACCOUNT_NUMBER#1]"),
    ("SR-40102", "SR-40102"),
    ("TXN-88213", "TXN-88213"),
    ("₹12,450", "₹12,450"),
    ("due on 2026-11-05", "due on 2026-11-05"),
    ("••• ••• 4012", "••• ••• 4012"),
    ("call 1800 210 4455", "call 1800 210 4455"),
    ("born 3rd of November 1985", "born [DOB#1]"),
    ("mobile-9876500002", "mobile-[MOBILE#1]"),  # only the bank reference prefixes are exempt
    ("Mob-98765 00002", "Mob-[MOBILE#1]"),
    ("CUST-1002", "CUST-1002"),
    ("PL-31002", "PL-31002"),
    ("ACC-20002", "ACC-20002"),
])
def test_redaction_catches_spoken_and_spaced_forms_and_keeps_bank_references(text, expected):
    assert redact_text(text, TODAY)[0] == expected


def test_only_known_reference_prefixes_exempt_a_number():
    kept = "SR-40102 TXN-88213 CUST-1002 PL-31002 ACC-20002 CMP-1 RQ-2 ESC-3 VL-4 HL-5 LA-6 HP-7 MP-8 CLM-9"
    assert redact_text(kept, TODAY)[0] == kept
    assert redact_text("ACC-123456789012 but XSR-9876500002", TODAY)[0] == "ACC-123456789012 but XSR-[MOBILE#1]"


def test_redact_text_reports_kinds_and_canonical_values():
    text = "Mobile +91 98765-00002, DOB 03/11/1985, born November 3, 1985, again 9876500002"
    out, found = redact_text(text, TODAY)
    assert out == "Mobile [MOBILE#1], DOB [DOB#1], born [DOB#1], again [MOBILE#1]"
    assert [(f.kind, f.value) for f in found] == [
        (PiiKind.MOBILE, MOBILE), (PiiKind.DOB, DOB_ISO), (PiiKind.DOB, DOB_ISO), (PiiKind.MOBILE, MOBILE)]
    assert text[found[0].start:found[0].end] == "+91 98765-00002"
    assert redact_text("a card 4111111111111111 and an account 123456789012", TODAY)[0] \
        == "a card [CARD#1] and an account [ACCOUNT_NUMBER#1]"
    assert redact_text("born on 2015-03-01", TODAY)[0] == "born on 2015-03-01"  # under 16 years old: kept
    assert redact_text("born on 2010-10-29", TODAY)[0] == "born on [DOB#1]"


def test_vault_is_a_separate_encrypted_file(client, tmp_path):
    cid = pii_call(client)
    vault_bytes = (tmp_path / "pii_vault.db").read_bytes()
    assert MOBILE.encode() not in vault_bytes and NAME.encode() not in vault_bytes
    assert b"pii_values" in vault_bytes
    with client.services.db.read() as con:
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "pii_values" not in tables
    assert MOBILE.encode() not in (tmp_path / "api.db").read_bytes()
    assert "[MOBILE#1]" in stored_transcript(client, cid)


def test_admin_can_reveal_and_it_is_audited(client):
    cid = pii_call(client)
    r = client.get(f"{BASE}/{cid}/pii", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json() == {"tokens": {
        "[MOBILE#1]": {"kind": "MOBILE", "value": MOBILE},
        "[DOB#1]": {"kind": "DOB", "value": DOB_ISO},
        "[NAME#1]": {"kind": "NAME", "value": NAME},
    }}
    events = [e for e in audit(client, cid) if e["action"] == AuditAction.PII_REVEALED]
    assert len(events) == 1 and events[0]["actor"] == "admin"
    assert MOBILE not in json.dumps(events[0]["payload"])
    assert client.get(f"{BASE}/{cid}/pii", headers=REVIEWER).status_code == 403
    assert client.get(f"{BASE}/{cid}/pii", headers=ANALYST).status_code == 403
    assert client.get(f"{BASE}/{cid}/pii", headers=VOICE).status_code == 403
    assert client.get(f"{BASE}/00000000-0000-0000-0000-000000000000/pii", headers=ADMIN).status_code == 404


def test_same_value_shares_a_token_across_turns_and_kinds_number_separately(client):
    cid = pii_call(client)
    turn(client, cid, "agent", "I will call you back on 9876500002 or 9123400005.")
    turns = json.loads(stored_transcript(client, cid))
    assert turns[1]["text"] == "I will call you back on [MOBILE#1] or [MOBILE#2]."
    tokens = client.get(f"{BASE}/{cid}/pii", headers=ADMIN).json()["tokens"]
    assert tokens["[MOBILE#2]"] == {"kind": "MOBILE", "value": "9123400005"}


def test_patch_meta_and_feedback_corrections_are_redacted(client):
    cid = start(client)
    turn(client, cid, "customer", "Hello")
    seq = turn(client, cid, "agent", "Sure.")
    p = client.patch(f"{BASE}/{cid}/turns/1/meta", json={"callback_mobile": "+91 9876500002", "intents": ["X"]},
                     headers=VOICE)
    assert p.status_code == 200 and p.json()["meta"] == {"callback_mobile": "[MOBILE#1]", "intents": ["X"]}
    f = client.post(f"{BASE}/{cid}/turns/{seq}/feedback",
                    json={"verdict": "BAD", "correction": "Should have read back 9876500002."}, headers=REVIEWER)
    assert f.status_code == 201, f.text
    assert f.json()["correction"] == "Should have read back [MOBILE#1]."
    assert stored_correction(client, cid, seq) == "Should have read back [MOBILE#1]."
    assert MOBILE not in json.dumps(audit(client, cid))
    assert MOBILE not in stored_transcript(client, cid)


def test_voice_rating_comment_is_redacted(client):
    cid = start(client)
    turn(client, cid, "customer", "Hello")
    r = client.post(f"{BASE}/{cid}/rating", json={"score": 4, "comment": f"Good, but call me on {MOBILE} next time",
                                                   "source": "VOICE"}, headers=VOICE)
    assert r.status_code == 201, r.text
    assert r.json()["comment"] == "Good, but call me on [MOBILE#1] next time"
    with client.services.db.read() as con:
        stored = con.execute("SELECT comment FROM call_ratings WHERE call_id = ?", (cid,)).fetchone()["comment"]
    assert stored == "Good, but call me on [MOBILE#1] next time"
    assert MOBILE not in json.dumps(audit(client, cid))
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["rating"]["comment"] == stored
    assert client.get(f"{BASE}/{cid}/pii", headers=ADMIN).json()["tokens"]["[MOBILE#1]"]["value"] == MOBILE


def test_no_vault_key_still_redacts(make_client, caplog):
    with caplog.at_level(logging.WARNING):
        client = make_client(keyed=False)
    assert sum("PII_VAULT_KEY" in r.getMessage() for r in caplog.records) == 1
    cid = pii_call(client)
    raw = stored_transcript(client, cid)
    assert "[MOBILE#1]" in raw and MOBILE not in raw and NAME not in raw
    r = client.get(f"{BASE}/{cid}/pii", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["tokens"]["[MOBILE#1]"] == {"kind": "MOBILE", "value": None}
    assert r.json()["tokens"]["[NAME#1]"] == {"kind": "NAME", "value": None}


def test_vault_put_dedupes_and_round_trips(tmp_path):
    vault = PiiVault(tmp_path / "v.db", Fernet.generate_key().decode())
    assert vault.put("c1", PiiKind.MOBILE, MOBILE) == "[MOBILE#1]"
    assert vault.put("c1", PiiKind.MOBILE, MOBILE) == "[MOBILE#1]"
    assert vault.put("c1", PiiKind.MOBILE, "9123400005") == "[MOBILE#2]"
    assert vault.put("c1", PiiKind.NAME, NAME) == "[NAME#1]"
    assert vault.put("c2", PiiKind.MOBILE, MOBILE) == "[MOBILE#1]"  # numbering is per call
    assert vault.get_all("c1") == {"[MOBILE#1]": {"kind": "MOBILE", "value": MOBILE},
                                   "[MOBILE#2]": {"kind": "MOBILE", "value": "9123400005"},
                                   "[NAME#1]": {"kind": "NAME", "value": NAME}}
    vault.delete_call("c1")
    assert vault.get_all("c1") == {} and vault.get_all("c2") == {"[MOBILE#1]": {"kind": "MOBILE", "value": MOBILE}}
    raw = sqlite3.connect(str(tmp_path / "v.db"))
    cols = {r[1] for r in raw.execute("PRAGMA table_info(pii_values)")}
    assert cols == {"call_id", "token", "kind", "value_hmac", "ciphertext", "created_at"}


def test_redactor_walks_meta_and_keeps_tool_names(tmp_path):
    vault = PiiVault(tmp_path / "v.db", Fernet.generate_key().decode())
    out = Redactor(vault, "c1", TODAY).redact({"text": SPOKEN, "n": 9876500002, "meta": META, "ok": True})
    assert out["text"] == "My number is [MOBILE#1] and I was born on [DOB#1]"
    assert out["n"] == "[MOBILE#1]"
    assert out["meta"]["tool_trace"][0]["name"] == "verify_customer"
    assert out["meta"]["retrieved"]["verify_customer"]["customer"]["first_name"] == "[NAME#1]"
    assert out["ok"] is True and out["meta"]["refs"] == ["SR-40102"]


def test_redact_existing_is_idempotent(client, tmp_path):
    cid = start(client)
    turn(client, cid, "customer", "Hello")
    turn(client, cid, "agent", "Sure.")
    raw_turns = [{"seq": 1, "role": "customer", "text": SPOKEN, "at": "2026-10-31T06:00:01Z", "meta": META},
                 {"seq": 2, "role": "agent", "text": "Noted, I will call 9876500002 back.", "at": "2026-10-31T06:00:02Z",
                  "meta": {}}]
    with client.services.db.tx() as con:  # a transcript written before redaction existed
        con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (json.dumps(raw_turns), cid))
        con.execute("INSERT INTO turn_feedback (call_id, seq, author, verdict, correction, at)"
                    " VALUES (?, 2, 'reviewer', 'BAD', ?, '2026-10-31T06:00:03Z')", (cid, f"Call {MOBILE} back"))
        con.execute("INSERT INTO call_ratings (call_id, score, comment, source, author, at)"
                    " VALUES (?, 3, ?, 'VOICE', 'voice', '2026-10-31T06:00:04Z')", (cid, f"My number is {MOBILE}"))
    vault = client.services.vault
    first = redact_all(client.services.db, vault, TODAY)
    assert first == {"calls": 1, "turns": 2, "ratings": 1, "feedback": 1}
    after_first = stored_transcript(client, cid)
    assert MOBILE not in after_first and NAME not in after_first
    assert json.loads(after_first)[1]["text"] == "Noted, I will call [MOBILE#1] back."
    assert stored_correction(client, cid, 2) == "Call [MOBILE#1] back"
    with client.services.db.read() as con:
        assert con.execute("SELECT comment FROM call_ratings WHERE call_id = ?", (cid,)).fetchone()["comment"] \
            == "My number is [MOBILE#1]"
    second = redact_all(client.services.db, vault, TODAY)
    assert second == {"calls": 0, "turns": 0, "ratings": 0, "feedback": 0}
    assert stored_transcript(client, cid) == after_first
    assert vault.get_all(cid)["[MOBILE#1]"]["value"] == MOBILE
