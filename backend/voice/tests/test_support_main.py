import json

import httpx
from fastapi.testclient import TestClient
from pipecat.frames.frames import TranscriptionFrame

from app import main
from app.api_client import SupportCallsApi
from app.config import Settings
from app.simulator_client import SimulatorClient
from app.speech import is_phantom, keep_transcript
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_tools import FakeSimulator

CALL = "55555555-5555-5555-5555-555555555555"


def client(llm):
    spring = []

    def handler(r: httpx.Request) -> httpx.Response:
        spring.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        if r.method == "POST" and r.url.path.endswith("/support/calls"):
            return httpx.Response(201, json={"id": CALL})
        return httpx.Response(200, json={})

    main.state.llm = llm
    main.state.sim = SimulatorClient(Settings(), transport=httpx.MockTransport(FakeSimulator()))
    main.state.support_calls = SupportCallsApi(Settings(), transport=httpx.MockTransport(handler))
    main.state.support.clear()
    main.state.classifier = lambda: None
    return TestClient(main.app), spring


def test_text_call_turn_and_end_record_a_support_call():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}),
                   tool_call("get_loans", {"product_type": "vehicle"}, "c2"), text("Your vehicle loan EMI is nine thousand eight hundred rupees."))
    c, spring = client(llm)
    started = c.post("/support/text-call").json()
    assert started["call_id"] == CALL and "Azentio Demo Bank" in started["greeting"]
    turn = c.post("/support/text-turn", json={"call_id": CALL, "text": "9876500002, 3 Nov 85, vehicle loan EMI?"}).json()
    assert turn["verified"] is True and turn["retrieved"]["get_loans"]["items"][0]["loan_id"] == "VL-31003"
    assert [t["name"] for t in turn["tool_trace"]] == ["verify_customer", "get_loans"]
    assert [t["outcome"] for t in turn["tool_trace"]] == ["OK", "OK"]
    assert c.post("/support/end", json={"call_id": CALL}).json() == {"outcome": "RESOLVED"}
    assert ("POST", "/api/v1/support/calls", {"channel": "TEXT"}) in spring
    assert spring[-1][1].endswith(f"/support/calls/{CALL}/end")


def test_blank_and_unknown_support_turns_are_rejected():
    c, _ = client(Scripted())
    assert c.post("/support/text-turn", json={"call_id": CALL, "text": "  "}).status_code == 400
    assert c.post("/support/text-turn", json={"call_id": CALL, "text": "hi"}).status_code == 404
    assert c.post("/support/end", json={"call_id": CALL}).status_code == 404


def test_phantom_transcripts_are_dropped():
    assert is_phantom("Thank you.") and is_phantom("  ") and is_phantom("Thanks for watching!")
    assert not is_phantom("Thank you, and when is my EMI?")
    assert keep_transcript(TranscriptionFrame("you", "u", "t")) is None
    assert keep_transcript(TranscriptionFrame("When is my next EMI?", "u", "t")) == "When is my next EMI?"


def test_unknown_outcome_is_rejected_at_the_boundary():
    c, _ = client(Scripted())
    c.post("/support/text-call")
    assert c.post("/support/end", json={"call_id": CALL, "outcome": "WAIVED"}).status_code == 422
    assert c.post("/support/end", json={"call_id": CALL, "outcome": "ESCALATED"}).json() == {"outcome": "ESCALATED"}
