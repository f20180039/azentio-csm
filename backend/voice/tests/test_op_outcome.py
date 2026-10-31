"""Task L5: every tool call in a turn's tool_trace carries an operation outcome (OK / FAILED / DECLINED)."""
import asyncio
import json

import httpx

from app.api_client import SupportCallsApi
from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import SupportBrain, op_outcome
from app.support_tools import CallSession
from app.vocab import OpOutcome, ToolError
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_brain import CALL
from tests.test_support_tools import FakeSimulator


def test_op_outcome_classifies_results():
    assert op_outcome({"items": []}) == OpOutcome.OK
    assert op_outcome({"ref": "SR-40200"}) == OpOutcome.OK
    for failed in (ToolError.SYSTEM_UNAVAILABLE, ToolError.BAD_ARGUMENTS, ToolError.UNKNOWN_TOOL, "HTTP_503", "HTTP_500"):
        assert op_outcome({"error": failed}) == OpOutcome.FAILED, failed
    for declined in (ToolError.NOT_VERIFIED, ToolError.LOCKED, ToolError.NOT_YOUR_RECORD, ToolError.VERIFICATION_FAILED,
                     ToolError.ASK_FIRST, "HTTP_404", "HTTP_409"):
        assert op_outcome({"error": declined}) == OpOutcome.DECLINED, declined
    assert [o.value for o in OpOutcome] == ["OK", "FAILED", "DECLINED"]


def test_trace_entries_carry_outcome():
    sim = FakeSimulator()
    faq_calls = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal faq_calls
        if request.url.path.endswith("/faq/search"):
            faq_calls += 1
            if faq_calls == 2:
                return httpx.Response(503, json={"error": "DOWN"})  # the simulator is down for the second lookup
        return sim(request)

    llm = Scripted(tool_call("search_faq", {"query": "savings interest rate"}),
                   tool_call("search_faq", {"query": "fixed deposit rate"}, "c2"),
                   text("The savings rate is on the FAQ; I can't reach the deposit rates right now."))
    spring: list[tuple[str, str, dict | None]] = []

    def spring_handler(r: httpx.Request) -> httpx.Response:
        spring.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        return httpx.Response(200, json={})

    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(flaky)),
                         SupportCallsApi(Settings(), transport=httpx.MockTransport(spring_handler)), CallSession(CALL))
    asyncio.run(brain.reply("What are your savings and FD rates?"))
    agent_posts = [b for m, p, b in spring if m == "POST" and p.endswith("/turns") and b and b["role"] == "agent"]
    trace = agent_posts[-1]["meta"]["tool_trace"]
    assert [t["name"] for t in trace] == ["search_faq", "search_faq"]
    assert [t["outcome"] for t in trace] == ["OK", "FAILED"]
    assert trace[1]["result_summary"] == "error SYSTEM_UNAVAILABLE"
