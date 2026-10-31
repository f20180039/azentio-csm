import asyncio
import json
from dataclasses import dataclass

import httpx

from app.api_client import SupportCallsApi
from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import SupportBrain, outcome_for, summarise
from app.support_prompt import support_prompt
from app.support_tools import CallSession
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_tools import FakeSimulator

CALL = "33333333-3333-3333-3333-333333333333"


@dataclass
class Found:
    intents: list
    source: str


def make(llm, classify=None):
    sim = FakeSimulator()
    spring: list[tuple[str, str, dict | None]] = []

    def spring_handler(r: httpx.Request) -> httpx.Response:
        spring.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        return httpx.Response(200, json={})

    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)),
                         SupportCallsApi(Settings(), transport=httpx.MockTransport(spring_handler)), CallSession(CALL), classify)
    return brain, sim, spring


def tools_called(sim):
    return [(r.url.path, dict(r.url.params)) for r in sim.requests]


def test_correction_requeries_the_vehicle_loan_without_reverifying():
    llm = Scripted(
        tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}), tool_call("get_loans", {"product_type": "personal"}, "c2"),
        text("Your personal loan instalment of twelve thousand four hundred fifty rupees is due on 5 November."),
        tool_call("get_loans", {"product_type": "vehicle"}, "c3"),
        text("Your vehicle loan instalment of nine thousand eight hundred rupees is due on 12 November."),
    )
    brain, sim, _ = make(llm)
    asyncio.run(brain.reply("My number is 98765 00002, born third November 85. When is my personal loan EMI?"))
    turn = asyncio.run(brain.reply("No, I meant my vehicle loan, not my personal loan."))
    assert [p for p, q in tools_called(sim) if p.endswith("/verify")] == ["/v1/verify"]  # verified once
    assert tools_called(sim)[-1] == ("/v1/lms/loans", {"type": "vehicle"})
    assert turn.verified and turn.retrieved()["get_loans"]["items"][0]["loan_id"] == "VL-31003"


def test_unsupported_after_a_request_keeps_the_ticket_and_routes_the_query():
    llm = Scripted(
        tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}),
        tool_call("create_service_request", {"category": "STATEMENT", "summary": "loan statement"}, "c2"),
        text("Done, your reference is S R four zero two zero zero."),
        tool_call("route_unsupported", {"query_text": "book me a flight to Dubai", "reason": "travel booking is not a bank service"}, "c3"),
        text("I can't book flights, but I've noted your request. Anything else about your accounts?"),
    )
    brain, _, spring = make(llm)
    asyncio.run(brain.reply("I'm 9876500002, 3 Nov 1985, please send my loan statement"))
    asyncio.run(brain.reply("Also can you book me a flight to Dubai?"))
    assert brain.call.refs == ["SR-40200", "RQ-60200"]
    assert asyncio.run(brain.finish()) == "TICKET_CREATED"
    assert spring[-1] == ("POST", f"/api/v1/support/calls/{CALL}/end", {"outcome": "TICKET_CREATED"})


def test_turns_and_meta_are_recorded_in_order_with_intents_patched():
    async def classify(t, history):
        return Found(["REPAYMENT"], "rules")

    llm = Scripted(tool_call("get_loans", {}), text("I need to verify you first. What's your registered mobile number?"))
    brain, sim, spring = make(llm, classify)
    turn = asyncio.run(brain.reply("When is my next EMI?"))
    assert sim.requests == []  # unverified: the tool refused before any HTTP call
    assert turn.intents == ["REPAYMENT"] and turn.verified is False
    posts = [(m, p.rsplit("/", 2)[-2:], b) for m, p, b in spring]
    customer, agent, patch = posts
    assert customer[2]["role"] == "customer" and customer[2]["meta"]["verified"] is False
    assert agent[2]["role"] == "agent" and agent[2]["meta"]["tool_trace"][0]["result_summary"] == "error NOT_VERIFIED"
    assert patch[0] == "PATCH" and patch[1] == ["1", "meta"] and patch[2]["intents"] == ["REPAYMENT"]


def test_a_failing_classifier_never_costs_the_reply():
    async def broken(t, h):
        raise RuntimeError("boom")

    brain, _, _ = make(Scripted(text("How can I help?")), broken)
    turn = asyncio.run(brain.reply("hello"))
    assert turn.text == "How can I help?" and turn.intents == []


def test_spring_down_does_not_break_the_call():
    def down(_):
        raise httpx.ConnectError("refused")

    brain = SupportBrain(Scripted(text("Sure.")), SimulatorClient(Settings(), transport=httpx.MockTransport(FakeSimulator())),
                         SupportCallsApi(Settings(), transport=httpx.MockTransport(down)), CallSession(CALL))
    assert asyncio.run(brain.reply("hi")).text == "Sure."


def test_outcome_priority_and_summaries():
    assert outcome_for(["RQ-1", "SR-2"]) == "TICKET_CREATED"
    assert outcome_for(["SR-2", "ESC-3"]) == "ESCALATED"
    assert outcome_for([]) == "RESOLVED"
    assert summarise({"items": [{"loan_id": "PL-1"}, {"loan_id": "VL-2"}]}) == "2 item(s): PL-1, VL-2"
    assert summarise({"error": "LOCKED"}) == "error LOCKED"


def test_prompt_carries_the_rules_judges_check():
    p = support_prompt()
    for must in ("verify_customer", "route_unsupported", "clarifying question", "search_faq", "NOT_YOUR_RECORD", "never restart"):
        assert must.lower() in p.lower()


def test_window_keeps_recent_turns_whole_and_shortens_old_tool_results():
    from app.support_brain import window
    msgs = [{"role": "system", "content": "S"}]
    for n in range(10):
        msgs += [{"role": "user", "content": f"u{n}"},
                 {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{n}", "type": "function", "function": {"name": "get_loans", "arguments": "{}"}}]},
                 {"role": "tool", "tool_call_id": f"c{n}", "content": "x" * 2000},
                 {"role": "assistant", "content": f"a{n}"}]
    w = window(msgs, turns=3)
    assert w[0]["content"] == "S" and w[1] == {"role": "user", "content": "u7"}  # cut at a caller message
    tools = [m for m in w if m["role"] == "tool"]
    assert [len(t["content"]) for t in tools[:-1]] == [600 + len("…(shortened)")] * 2 and len(tools[-1]["content"]) == 2000
    assert all(any(t.get("tool_call_id") == c["id"] for t in tools) for m in w for c in m.get("tool_calls") or [])


def test_an_unsupported_request_the_model_did_not_route_is_routed_by_the_backstop():
    async def classify(t, history):
        return Found(["UNSUPPORTED"], "llm")

    brain, sim, _ = make(Scripted(text("Sorry, I can't give stock tips. I can help with loans or accounts.")), classify)
    turn = asyncio.run(brain.reply("Can you give me some stock tips?"))
    assert [t.name for t in turn.tool_calls] == ["route_unsupported"] and turn.refs == ["RQ-60200"]
    assert any(r.url.path.endswith("/csm/routed") for r in sim.requests)


def test_no_double_routing_when_the_model_already_routed():
    async def classify(t, history):
        return Found(["UNSUPPORTED"], "llm")

    llm = Scripted(tool_call("route_unsupported", {"query_text": "flight", "reason": "travel"}), text("I can't book flights."))
    brain, sim, _ = make(llm, classify)
    turn = asyncio.run(brain.reply("Book me a flight"))
    assert [t.name for t in turn.tool_calls] == ["route_unsupported"]
    assert sum(r.url.path.endswith("/csm/routed") for r in sim.requests) == 1
