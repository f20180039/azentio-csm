"""Level 2 §6: a reviewer corrects a caller turn's transcript while the recognised text stays on the record."""
import uuid

from conftest import ADMIN, ANALYST, REVIEWER, VOICE, audit
from test_support import BASE, end, start, turn

HEARD = "my number is 98765 0002"
CORRECTED = "my number is 98765 00002"
META_KEY = "transcript_correction"


def call_with_turns(client, customer_meta=None) -> str:
    cid = start(client)
    assert turn(client, cid, "customer", HEARD, customer_meta).status_code == 201
    assert turn(client, cid, "agent", "Thank you, let me check.").status_code == 201
    return cid


def correct(client, cid, seq, text=CORRECTED, who=REVIEWER):
    return client.put(f"{BASE}/{cid}/turns/{seq}/transcript", json={"text": text}, headers=who)


def clear(client, cid, seq, who=REVIEWER):
    return client.delete(f"{BASE}/{cid}/turns/{seq}/transcript", headers=who)


def get_turns(client, cid):
    r = client.get(f"{BASE}/{cid}", headers=ANALYST)
    assert r.status_code == 200, r.text
    return r.json()["turns"]


def test_reviewer_corrects_a_caller_turn_and_the_original_is_kept(make_client):
    client = make_client("2026-10-31T11:30:00")
    cid = call_with_turns(client, customer_meta={"intents": ["ACCOUNT"]})
    assert end(client, cid, "RESOLVED").status_code == 200  # corrections are allowed after the call has ended

    r = correct(client, cid, 1)
    assert r.status_code == 200, r.text
    assert r.json()["seq"] == 1 and r.json()["role"] == "customer"
    assert r.json()["text"] == HEARD
    assert r.json()["meta"][META_KEY] == {"text": CORRECTED, "author": "reviewer", "at": "2026-10-31T06:00:00Z"}
    assert r.json()["meta"]["intents"] == ["ACCOUNT"]  # shallow merge keeps the rest of the meta

    turns = get_turns(client, cid)
    assert turns[0]["text"] == HEARD
    assert turns[0]["meta"][META_KEY]["text"] == CORRECTED
    assert turns[0]["meta"][META_KEY]["author"] == "reviewer"
    assert META_KEY not in turns[1]["meta"]

    events = [e for e in audit(client, cid) if e["action"] == "transcript.corrected"]
    assert len(events) == 1
    assert events[0]["actor"] == "reviewer"
    assert events[0]["payload"] == {"seq": 1, "original": HEARD, "corrected": CORRECTED}


def test_agent_turns_and_unknown_turns_are_refused(client):
    cid = call_with_turns(client)
    r = correct(client, cid, 2)
    assert r.status_code == 400
    assert r.json()["detail"] == "Transcript corrections apply to caller turns"
    assert correct(client, cid, 3).status_code == 404
    assert correct(client, cid, 0).status_code == 404
    assert correct(client, str(uuid.uuid4()), 1).status_code == 404
    assert clear(client, cid, 2).status_code == 400
    assert clear(client, cid, 3).status_code == 404
    assert META_KEY not in get_turns(client, cid)[0]["meta"]


def test_analyst_cannot_correct(client):
    cid = call_with_turns(client)
    assert correct(client, cid, 1, who=ANALYST).status_code == 403
    assert correct(client, cid, 1, who=VOICE).status_code == 403
    assert client.put(f"{BASE}/{cid}/turns/1/transcript", json={"text": CORRECTED}).status_code == 401
    assert META_KEY not in get_turns(client, cid)[0]["meta"]

    assert correct(client, cid, 1, who=ADMIN).status_code == 200
    assert get_turns(client, cid)[0]["meta"][META_KEY]["author"] == "admin"
    assert clear(client, cid, 1, who=ANALYST).status_code == 403
    assert clear(client, cid, 1, who=VOICE).status_code == 403
    assert META_KEY in get_turns(client, cid)[0]["meta"]


def test_blank_text_is_422_or_400(client):
    cid = call_with_turns(client)
    for bad in ("", "   ", None, 123, True, ["x"], "x" * 2001):
        assert correct(client, cid, 1, text=bad).status_code == 400, bad
    assert client.put(f"{BASE}/{cid}/turns/1/transcript", json={}, headers=REVIEWER).status_code == 400
    assert META_KEY not in get_turns(client, cid)[0]["meta"]

    r = correct(client, cid, 1, text="  " + CORRECTED + "  ")
    assert r.status_code == 200 and r.json()["meta"][META_KEY]["text"] == CORRECTED
    assert correct(client, cid, 1, text="x" * 2000).status_code == 200


def test_correction_can_be_replaced_and_removed(make_client):
    client = make_client("2026-10-31T11:30:00")
    cid = call_with_turns(client, customer_meta={"verified": True})
    assert correct(client, cid, 1, text="first try").status_code == 200
    client.clock.set("2026-10-31T11:40:00")
    assert correct(client, cid, 1, who=ADMIN).status_code == 200

    meta = get_turns(client, cid)[0]["meta"]
    assert meta[META_KEY] == {"text": CORRECTED, "author": "admin", "at": "2026-10-31T06:10:00Z"}
    assert meta["verified"] is True

    r = clear(client, cid, 1)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == HEARD and META_KEY not in r.json()["meta"]
    meta = get_turns(client, cid)[0]["meta"]
    assert META_KEY not in meta and meta["verified"] is True
    assert clear(client, cid, 1).status_code == 404

    actions = [e["action"] for e in audit(client, cid)]
    assert actions.count("transcript.corrected") == 2
    assert actions.count("transcript.correction_removed") == 1
    removed = next(e for e in audit(client, cid) if e["action"] == "transcript.correction_removed")
    assert removed["payload"] == {"seq": 1, "original": HEARD, "corrected": CORRECTED}
