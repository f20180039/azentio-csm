"""Ratings, turn feedback, review queue, lessons and insights (shared contract, 31 Oct)."""
import sqlite3
import uuid

from conftest import ADMIN, ANALYST, REVIEWER, VOICE, audit
from test_support import BASE, end, start, turn

SUPPORT = "/api/v1/support"
DISSATISFIED_META = {"tool_trace": [
    {"name": "escalate_to_human", "args": {"trigger": "DISSATISFIED", "reason": "unhappy"}, "result_summary": "ok"}]}


def call_with_turns(client, agent_meta=None) -> str:
    cid = start(client)
    assert turn(client, cid, "customer", "Where is my refund?").status_code == 201
    assert turn(client, cid, "agent", "Let me check that.", agent_meta or {}).status_code == 201
    return cid


def rate(client, cid, score, source="PANEL", who=ANALYST, comment=None):
    return client.post(f"{BASE}/{cid}/rating", json={"score": score, "comment": comment, "source": source},
                       headers=who)


def feedback(client, cid, seq, verdict="BAD", who=REVIEWER, correction=None):
    return client.post(f"{BASE}/{cid}/turns/{seq}/feedback", json={"verdict": verdict, "correction": correction},
                       headers=who)


def propose(client, text="Confirm the account before quoting balances.", who=REVIEWER, **extra):
    return client.post(f"{SUPPORT}/lessons", json={"text": text, **extra}, headers=who)


def review_items(client, who=ANALYST):
    r = client.get(f"{SUPPORT}/review", headers=who)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# --- ratings -----------------------------------------------------------------------------------------------

def test_voice_rating_then_panel_rating_replaces_and_shows_on_call(make_client):
    client = make_client("2026-10-31T11:30:00")
    cid = call_with_turns(client)
    r = rate(client, cid, 4, source="VOICE", who=VOICE, comment="quick")
    assert r.status_code == 201
    assert r.json() == {"score": 4, "comment": "quick", "source": "VOICE", "at": "2026-10-31T06:00:00Z"}

    client.clock.set("2026-10-31T11:40:00")
    r = rate(client, cid, 2, who=REVIEWER)
    assert r.status_code == 201 and r.json()["score"] == 2 and r.json()["source"] == "PANEL"

    d = client.get(f"{BASE}/{cid}", headers=ANALYST).json()
    assert d["rating"] == {"score": 2, "comment": None, "source": "PANEL", "at": "2026-10-31T06:10:00Z"}
    assert client.get(BASE, headers=ANALYST).json()["items"][0]["rating"]["score"] == 2
    with sqlite3.connect(client.services.db.path) as con:
        assert con.execute("SELECT COUNT(*) FROM call_ratings").fetchone()[0] == 1
    assert [e["action"] for e in audit(client, cid)].count("rating.recorded") == 2


def test_rating_role_rules(client):
    cid = call_with_turns(client)
    assert rate(client, cid, 5, source="VOICE", who=ANALYST).status_code == 403
    assert rate(client, cid, 5, source="VOICE", who=ADMIN).status_code == 403
    assert rate(client, cid, 5, source="PANEL", who=VOICE).status_code == 403
    for who in (ANALYST, REVIEWER, ADMIN):
        assert rate(client, cid, 5, who=who).status_code == 201
    assert client.post(f"{BASE}/{cid}/rating", json={"score": 5, "source": "PANEL"}).status_code == 401


def test_rating_validation(client):
    cid = call_with_turns(client)
    for bad in (0, 6, -1, 3.5, "4", True, None):
        assert rate(client, cid, bad).status_code == 400, bad
    assert rate(client, cid, 3, source="SMS").status_code == 400
    assert rate(client, str(uuid.uuid4()), 3).status_code == 400
    assert client.get(f"{BASE}/{cid}", headers=ANALYST).json()["rating"] is None


# --- turn feedback -----------------------------------------------------------------------------------------

def test_feedback_replaces_per_author_and_shows_on_turn(make_client):
    client = make_client("2026-10-31T11:30:00")
    cid = call_with_turns(client)
    r = feedback(client, cid, 2, "BAD", correction="Ask for the reference number first.")
    assert r.status_code == 201
    assert r.json() == {"seq": 2, "verdict": "BAD", "correction": "Ask for the reference number first.",
                        "author": "reviewer", "at": "2026-10-31T06:00:00Z"}
    assert feedback(client, cid, 2, "GOOD").status_code == 201
    assert feedback(client, cid, 2, "BAD", who=ADMIN).status_code == 201

    turns = client.get(f"{BASE}/{cid}", headers=ANALYST).json()["turns"]
    assert turns[0]["feedback"] == []
    by_author = {f["author"]: f for f in turns[1]["feedback"]}
    assert set(by_author) == {"reviewer", "admin"}
    assert by_author["reviewer"]["verdict"] == "GOOD" and by_author["reviewer"]["correction"] is None
    assert [e["action"] for e in audit(client, cid)].count("feedback.recorded") == 3


def test_feedback_refusals(client):
    cid = call_with_turns(client)
    assert feedback(client, cid, 2, who=ANALYST).status_code == 403
    assert feedback(client, cid, 2, who=VOICE).status_code == 403
    assert feedback(client, cid, 1).status_code == 400
    assert feedback(client, cid, 3).status_code == 404
    assert feedback(client, cid, 0).status_code == 404
    assert feedback(client, str(uuid.uuid4()), 1).status_code == 404
    assert feedback(client, cid, 2, verdict="MEH").status_code == 400


# --- review queue ------------------------------------------------------------------------------------------

def test_review_reasons_and_ordering(make_client):
    client = make_client("2026-10-31T10:00:00")
    low = call_with_turns(client)
    rate(client, low, 2)
    client.clock.set("2026-10-31T10:05:00")
    unhappy = call_with_turns(client, DISSATISFIED_META)
    client.clock.set("2026-10-31T10:10:00")
    bad = call_with_turns(client)
    feedback(client, bad, 2, "BAD")
    client.clock.set("2026-10-31T10:15:00")
    fine = call_with_turns(client, {"tool_trace": [
        {"name": "escalate_to_human", "args": {"trigger": "CUSTOMER_REQUEST"}}]})
    rate(client, fine, 3)
    feedback(client, fine, 2, "GOOD")
    client.clock.set("2026-10-31T10:20:00")
    everything = call_with_turns(client, DISSATISFIED_META)
    rate(client, everything, 1, source="VOICE", who=VOICE)
    feedback(client, everything, 2, "BAD")
    end(client, everything, "ESCALATED")

    items = review_items(client)
    assert [i["id"] for i in items] == [everything, bad, unhappy, low]
    by_id = {i["id"]: i for i in items}
    assert by_id[low]["reasons"] == ["LOW_RATING"] and by_id[low]["rating"]["score"] == 2
    assert by_id[unhappy]["reasons"] == ["DISSATISFIED"] and by_id[unhappy]["rating"] is None
    assert by_id[bad]["reasons"] == ["BAD_FEEDBACK"]
    assert by_id[everything]["reasons"] == ["LOW_RATING", "DISSATISFIED", "BAD_FEEDBACK"]
    assert by_id[everything]["outcome"] == "ESCALATED"
    assert by_id[everything]["startedAt"] == "2026-10-31T04:50:00Z"
    assert all(i["resolved"] is False for i in items)

    r = client.post(f"{SUPPORT}/review/{everything}/resolve", json={"note": "Coached on refunds."}, headers=REVIEWER)
    assert r.status_code == 200 and r.json()["resolved"] is True
    items = review_items(client)
    assert [i["id"] for i in items] == [bad, unhappy, low, everything]
    assert items[-1]["resolved"] is True
    assert len(review_items(client)) == 4
    assert [i["id"] for i in client.get(f"{SUPPORT}/review", params={"limit": 2}, headers=ANALYST).json()["items"]] \
        == [bad, unhappy]
    assert "review.resolved" in [e["action"] for e in audit(client, everything)]


def test_dissatisfied_only_counts_agent_turns(client):
    cid = start(client)
    turn(client, cid, "customer", "I am unhappy", DISSATISFIED_META)
    assert review_items(client) == []


def test_review_refusals(client):
    cid = call_with_turns(client)
    assert client.get(f"{SUPPORT}/review", headers=VOICE).status_code == 403
    assert client.get(f"{SUPPORT}/review", params={"limit": 0}, headers=ANALYST).status_code == 400
    url = f"{SUPPORT}/review/{cid}/resolve"
    assert client.post(url, json={"note": "x"}, headers=ANALYST).status_code == 403
    assert client.post(url, json={"note": "x"}, headers=VOICE).status_code == 403
    assert client.post(url, json={}, headers=REVIEWER).status_code == 400
    assert client.post(f"{SUPPORT}/review/{uuid.uuid4()}/resolve", json={"note": "x"},
                       headers=ADMIN).status_code == 404


# --- lessons -----------------------------------------------------------------------------------------------

def test_lesson_lifecycle_and_active_filter(make_client):
    client = make_client("2026-10-31T12:00:00")
    cid = call_with_turns(client)
    r = propose(client, sourceCallId=cid, sourceSeq=2)
    assert r.status_code == 201
    lesson = r.json()
    assert lesson["status"] == "PROPOSED" and lesson["author"] == "reviewer" and lesson["approvedBy"] is None
    assert lesson["sourceCallId"] == cid and lesson["sourceSeq"] == 2
    assert lesson["createdAt"] == "2026-10-31T06:30:00Z"
    other = propose(client, text="Offer an SMS summary at the end.", who=ADMIN).json()
    assert other["sourceCallId"] is None and other["sourceSeq"] is None

    assert client.get(f"{SUPPORT}/lessons", params={"active": "true"}, headers=VOICE).json()["items"] == []
    r = client.patch(f"{SUPPORT}/lessons/{lesson['id']}", json={"status": "ACTIVE"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["approvedBy"] == "admin"

    active = client.get(f"{SUPPORT}/lessons", params={"active": "true"}, headers=VOICE).json()["items"]
    assert [x["id"] for x in active] == [lesson["id"]]
    assert len(client.get(f"{SUPPORT}/lessons", headers=ANALYST).json()["items"]) == 2

    r = client.patch(f"{SUPPORT}/lessons/{lesson['id']}", json={"status": "RETIRED"}, headers=ADMIN)
    assert r.json()["status"] == "RETIRED" and r.json()["approvedBy"] == "admin"
    assert client.get(f"{SUPPORT}/lessons", params={"active": "true"}, headers=VOICE).json()["items"] == []

    changes = [e for e in audit(client, cid) if e["action"] == "lesson.status_changed"]
    assert [(e["payload"]["from"], e["payload"]["to"]) for e in changes] == [("PROPOSED", "ACTIVE"),
                                                                            ("ACTIVE", "RETIRED")]


def test_lesson_refusals(client):
    cid = call_with_turns(client)
    assert propose(client, text="too short").status_code == 400
    assert propose(client, text="x" * 301).status_code == 400
    assert propose(client, text=None).status_code == 400
    assert propose(client, text="x" * 300).status_code == 201
    assert propose(client, text="x" * 10).status_code == 201
    assert propose(client, who=ANALYST).status_code == 403
    assert propose(client, who=VOICE).status_code == 403
    assert propose(client, sourceCallId=str(uuid.uuid4())).status_code == 400
    assert propose(client, sourceCallId=cid, sourceSeq=9).status_code == 400
    assert propose(client, sourceSeq=1).status_code == 400

    lid = propose(client).json()["id"]
    url = f"{SUPPORT}/lessons/{lid}"
    assert client.patch(url, json={"status": "ACTIVE"}, headers=REVIEWER).status_code == 403
    assert client.patch(url, json={"status": "ACTIVE"}, headers=VOICE).status_code == 403
    assert client.patch(url, json={"status": "PROPOSED"}, headers=ADMIN).status_code == 400
    assert client.patch(url, json={"status": "DONE"}, headers=ADMIN).status_code == 400
    assert client.patch(f"{SUPPORT}/lessons/nope", json={"status": "ACTIVE"}, headers=ADMIN).status_code == 404
    assert client.get(f"{SUPPORT}/lessons").status_code == 401


# --- insights ----------------------------------------------------------------------------------------------

def test_insights_from_seeded_data(client):
    empty = client.get(f"{SUPPORT}/insights", headers=ANALYST).json()
    assert empty == {"ratings": {"count": 0, "average": None,
                                 "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
                     "lowRated": 0, "openReviews": 0, "badFeedback": 0, "activeLessons": 0}

    calls = [call_with_turns(client) for _ in range(4)]
    for cid, score in zip(calls, (1, 2, 4, 5)):
        assert rate(client, cid, score).status_code == 201
    feedback(client, calls[2], 2, "BAD")
    feedback(client, calls[2], 2, "BAD", who=ADMIN)
    feedback(client, calls[3], 2, "GOOD")
    client.post(f"{SUPPORT}/review/{calls[0]}/resolve", json={"note": "done"}, headers=ADMIN)
    lid = propose(client).json()["id"]
    propose(client)
    client.patch(f"{SUPPORT}/lessons/{lid}", json={"status": "ACTIVE"}, headers=ADMIN)

    i = client.get(f"{SUPPORT}/insights", headers=REVIEWER).json()
    assert i["ratings"] == {"count": 4, "average": 3.0, "distribution": {"1": 1, "2": 1, "3": 0, "4": 1, "5": 1}}
    assert i["lowRated"] == 2
    assert i["openReviews"] == 2
    assert i["badFeedback"] == 2
    assert i["activeLessons"] == 1
    assert client.get(f"{SUPPORT}/insights", headers=VOICE).status_code == 403


# --- audit chain and schema ---------------------------------------------------------------------------------

def test_audit_chain_stays_valid(client):
    cid = call_with_turns(client, DISSATISFIED_META)
    rate(client, cid, 1, source="VOICE", who=VOICE)
    feedback(client, cid, 2, "BAD")
    client.post(f"{SUPPORT}/review/{cid}/resolve", json={"note": "ok"}, headers=REVIEWER)
    lid = propose(client, sourceCallId=cid).json()["id"]
    client.patch(f"{SUPPORT}/lessons/{lid}", json={"status": "ACTIVE"}, headers=ADMIN)
    acts = [e["action"] for e in audit(client, cid)]
    for a in ("rating.recorded", "feedback.recorded", "review.resolved", "lesson.proposed",
              "lesson.status_changed"):
        assert a in acts
    v = client.get("/api/v1/audit/verify", headers=ADMIN).json()
    assert v["valid"] is True and v["checked"] >= len(acts)


def test_schema_is_idempotent_on_existing_database(make_client):
    first = make_client(db_name="shared.db")
    cid = call_with_turns(first)
    rate(first, cid, 2)
    second = make_client(db_name="shared.db")
    assert second.get(f"{BASE}/{cid}", headers=ANALYST).json()["rating"]["score"] == 2
