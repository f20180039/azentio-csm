"""Level 2: the complaint carries the caller's own words and the record it is about; the escalation carries why and
which records; the agent knows how to explain every ticket status."""
import asyncio
import json

import httpx

from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import SupportBrain
from app.support_prompt import support_prompt
from app.support_tools import SUPPORT_TOOL_SCHEMAS, CallSession, run_support_tool
from app.vocab import EscalationTrigger, SupportTool
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_tools import FakeSimulator

CALL = "44444444-4444-4444-4444-444444444444"
CALLER_SAID = "my fifteen thousand transfer failed"


def make(llm, call: CallSession):
    sim = FakeSimulator()
    return SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), None, call), sim


def body_of(sim: FakeSimulator, path: str) -> dict:
    return next(json.loads(r.content) for r in sim.requests if r.url.path == path and r.method == "POST")


def test_complaint_sends_the_callers_words_and_reference():
    llm = Scripted(tool_call(SupportTool.REGISTER_COMPLAINT, {"category": "FAILED_TRANSACTION", "description": "Transfer of ₹15,000 failed",
                                                             "severity": "MEDIUM", "related_ref": "TXN-88213"}),
                   text("I've registered complaint C M P five zero two zero zero."))
    brain, sim = make(llm, CallSession(CALL, session="tok"))
    turn = asyncio.run(brain.reply(CALLER_SAID))
    body = body_of(sim, "/v1/csm/complaints")
    assert body["original_statement"] == CALLER_SAID and body["related_ref"] == "TXN-88213"
    assert body["category"] == "FAILED_TRANSACTION" and body["description"] == "Transfer of ₹15,000 failed"
    assert turn.refs == ["CMP-50200"] and brain.call.last_caller_text == CALLER_SAID


def test_complaint_without_a_reference_sends_none_not_a_crash():
    sim = FakeSimulator()
    client, call = SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), CallSession(CALL, session="tok")
    out = asyncio.run(run_support_tool(client, call, SupportTool.REGISTER_COMPLAINT,
                                       {"category": "SERVICE_EXPERIENCE", "description": "rude branch staff", "severity": "LOW"}))
    assert out["ref"] == "CMP-50200"
    body = body_of(sim, "/v1/csm/complaints")
    assert body["related_ref"] is None and body["original_statement"] is None  # nothing heard yet: no empty strings on the record


def test_escalation_sends_trigger_as_category_and_the_calls_refs():
    sim = FakeSimulator()
    client, call = SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), CallSession(CALL, session="tok", refs=["SR-40200"])
    out = asyncio.run(run_support_tool(client, call, SupportTool.ESCALATE_TO_HUMAN,
                                       {"trigger": "UNRESOLVED", "reason": "could not change the address", "summary": "address change"}))
    assert out["ref"] == "ESC-70200"
    body = body_of(sim, "/v1/csm/escalations")
    assert body["category"] == "UNRESOLVED" and body["related_refs"] == ["SR-40200"]
    assert body["reason"] == "UNRESOLVED: could not change the address" and body["summary"] == "address change"


def test_tool_schema_does_not_offer_backstop_triggers():
    assert {EscalationTrigger.AUTH_LOCKED, EscalationTrigger.REPEATED_MISUNDERSTANDING} <= set(EscalationTrigger)
    schema = next(t for t in SUPPORT_TOOL_SCHEMAS if t["function"]["name"] == SupportTool.ESCALATE_TO_HUMAN)
    offered = set(schema["function"]["parameters"]["properties"]["trigger"]["enum"])
    assert offered == {"CUSTOMER_REQUEST", "DISSATISFIED", "UNRESOLVED", "SENSITIVE"}
    assert "AUTH_LOCKED" not in offered and "REPEATED_MISUNDERSTANDING" not in offered
    assert "related_refs" not in schema["function"]["parameters"]["properties"]  # the tool fills related_refs from the call itself


def test_complaint_schema_offers_an_optional_related_reference():
    complaint = next(t for t in SUPPORT_TOOL_SCHEMAS if t["function"]["name"] == SupportTool.REGISTER_COMPLAINT)["function"]["parameters"]
    assert "TXN-88213" in complaint["properties"]["related_ref"]["description"]
    assert "related_ref" not in complaint["required"]


def test_prompt_tells_the_agent_how_to_report_ticket_status():
    p = support_prompt()
    assert "REQUEST STATUS" in p and "AWAITING_INFO" in p and "REJECTED" in p
    assert "IN_PROGRESS" in p and "RESOLVED or CLOSED" in p and "offer to escalate" in p
    assert p.index("SERVICE REQUESTS:") < p.index("REQUEST STATUS:") < p.index("COMPLAINTS:")
