import asyncio
import json

import httpx

from app.config import Settings
from app.simulator_client import SESSION_HEADER, SimulatorClient
from app.support_tools import SUPPORT_TOOL_SCHEMAS, CallSession, run_support_tool

CALL = "22222222-2222-2222-2222-222222222222"


class FakeSimulator:
    """Just enough of the bank simulator contract: CUST-1002 owns PL-31002 and VL-31003; VL-31007 belongs to someone else."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.failures = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1")
        if path == "/verify":
            body = json.loads(request.content)
            if self.failures >= 3:
                return httpx.Response(423, json={"error": "LOCKED"})
            if body["mobile"] == "9876500002" and body["dob"] == "1985-11-03":
                return httpx.Response(200, json={"session": "tok", "expires_in": 900, "customer": {"customer_ref": "CUST-1002", "first_name": "Rahul"}})
            self.failures += 1
            return httpx.Response(401, json={"error": "VERIFICATION_FAILED", "attempts_left": 3 - self.failures})
        if path == "/faq/search":
            q = request.url.params["q"]
            return httpx.Response(200, json={"items": [] if "weather" in q else [{"id": "FAQ-004", "question": "q", "answer": "a", "score": 3.1}]})
        if path == "/csm/routed":
            return httpx.Response(201, json={"ref": "RQ-60200"})
        if path == "/csm/escalations":
            return httpx.Response(201, json={"ref": "ESC-70200"})
        if request.headers.get(SESSION_HEADER) != "tok":
            return httpx.Response(401, json={"error": "NOT_VERIFIED"})
        if path == "/lms/loans":
            loans = [{"loan_id": "PL-31002", "product_type": "personal", "next_instalment": {"amount": 12450, "due_date": "2026-11-05"}},
                     {"loan_id": "VL-31003", "product_type": "vehicle", "next_instalment": {"amount": 9800, "due_date": "2026-11-12"}}]
            t = request.url.params.get("type")
            return httpx.Response(200, json={"items": [x for x in loans if not t or x["product_type"] == t]})
        if path == "/lms/loans/VL-31007/schedule":
            return httpx.Response(403, json={"error": "NOT_YOUR_RECORD"})
        if path == "/csm/complaints" and request.method == "POST":
            return httpx.Response(201, json={"ref": "CMP-50200", "status": "OPEN"})
        if path == "/csm/complaints/CMP-50011" and request.method == "GET":
            return httpx.Response(200, json={"ref": "CMP-50011", "category": "INCORRECT_CHARGE", "status": "OPEN"})
        if path == "/csm/tickets/SR-40200" and request.method == "GET":
            return httpx.Response(200, json={"ref": "SR-40200", "category": "REPAYMENT_SCHEDULE", "status": "OPEN",
                                             "details": {"loan_id": "VL-31003"}})
        if path == "/csm/tickets" and request.method == "POST":
            return httpx.Response(201, json={"ref": "SR-40200", "status": "OPEN", "eta_days": 2})
        return httpx.Response(404, json={"error": "NOT_FOUND"})


def setup():
    sim = FakeSimulator()
    # spoke_numbers: these tests drive the tool directly, standing in for a caller who did say their details aloud
    return sim, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), CallSession(CALL, spoke_numbers=True)


def run(client, call, name, args=None):
    return asyncio.run(run_support_tool(client, call, name, args or {}))


def verify(client, call, dob="1985-11-03"):
    return run(client, call, "verify_customer", {"mobile": "+91 98765 00002", "date_of_birth": dob})


def test_personal_tools_refuse_without_verification_and_make_no_request():
    sim, client, call = setup()
    for name in ("get_loans", "get_accounts", "get_ticket", "create_service_request", "get_claims"):
        assert run(client, call, name, {"ref": "SR-1", "category": "STATEMENT", "summary": "s"})["error"] == "NOT_VERIFIED"
    assert sim.requests == []


def test_verify_then_filter_loans_by_type_with_spoken_amounts():
    sim, client, call = setup()
    assert verify(client, call)["verified"] is True and call.verified
    assert json.loads(sim.requests[0].content)["mobile"] == "9876500002"  # +91 and spaces stripped
    out = run(client, call, "get_loans", {"product_type": "vehicle"})
    assert [x["loan_id"] for x in out["items"]] == ["VL-31003"]
    assert out["items"][0]["next_instalment"]["amount_spoken"] == "nine thousand eight hundred rupees"


def test_someone_elses_record_is_declined():
    _, client, call = setup()
    verify(client, call)
    out = run(client, call, "get_schedule", {"loan_id": "VL-31007"})
    assert out["error"] == "NOT_YOUR_RECORD" and "Decline" in out["note"]


def test_three_failures_lock_and_personal_tools_keep_refusing():
    sim, client, call = setup()
    for _ in range(2):
        assert verify(client, call, dob="1990-01-01")["error"] == "VERIFICATION_FAILED"
    assert not call.locked
    third = verify(client, call, dob="1990-01-01")  # no attempts left: locked at once, not on a fourth try
    assert third["error"] == "LOCKED" and call.locked and call.verify_failures == 3
    assert verify(client, call)["error"] == "LOCKED"
    before = len(sim.requests)
    assert run(client, call, "get_loans")["error"] == "LOCKED"
    assert len(sim.requests) == before


def test_faq_without_an_approved_answer_says_so():
    _, client, call = setup()
    assert run(client, call, "search_faq", {"query": "documents for vehicle loan"})["items"][0]["id"] == "FAQ-004"
    assert run(client, call, "search_faq", {"query": "weather today"})["no_approved_answer"] is True


def test_refs_are_collected_and_routing_needs_no_verification():
    _, client, call = setup()
    assert run(client, call, "route_unsupported", {"query_text": "book a flight", "reason": "not a banking service"})["ref"] == "RQ-60200"
    verify(client, call)
    assert run(client, call, "create_service_request", {"category": "STATEMENT", "summary": "loan statement"})["ref"] == "SR-40200"
    assert call.refs == ["RQ-60200", "SR-40200"]


def test_bad_category_and_unreachable_simulator_do_not_raise():
    _, client, call = setup()
    verify(client, call)
    assert run(client, call, "create_service_request", {"category": "LOAN_WAIVER", "summary": "x"})["error"] == "BAD_ARGUMENTS"

    def down(_):
        raise httpx.ConnectError("refused")
    call2 = CallSession(CALL, session="tok")
    client2 = SimulatorClient(Settings(), transport=httpx.MockTransport(down))
    assert run(client2, call2, "get_loans")["error"] == "SYSTEM_UNAVAILABLE"


def test_schemas_cover_every_tool():
    names = {t["function"]["name"] for t in SUPPORT_TOOL_SCHEMAS}
    assert {"verify_customer", "search_faq", "route_unsupported", "escalate_to_human", "create_service_request", "end_call"} <= names


def test_a_first_request_for_a_person_is_answered_with_a_question_not_a_handover():
    sim, client, call = setup()
    out = run(client, call, "escalate_to_human", {"trigger": "CUSTOMER_REQUEST", "reason": "wants a person", "summary": "asked for a human"})
    assert out["error"] == "ASK_FIRST" and "ask what they need" in out["note"]
    assert not [r for r in sim.requests if r.url.path.endswith("/escalations")]  # nothing raised yet
    second = run(client, call, "escalate_to_human", {"trigger": "CUSTOMER_REQUEST", "reason": "asked again", "summary": "insists on a person"})
    assert second.get("error") != "ASK_FIRST"


def test_sensitive_dissatisfied_and_unresolved_hand_over_at_once():
    for trigger in ("SENSITIVE", "DISSATISFIED", "UNRESOLVED"):
        sim, client, call = setup()
        run(client, call, "escalate_to_human", {"trigger": trigger, "reason": "r", "summary": "s"})
        assert [r for r in sim.requests if r.url.path.endswith("/escalations")], trigger


def test_handover_mode_follows_the_channel():
    sim, client, call = setup()
    sim_escalation = lambda r: httpx.Response(201, json={"ref": "ESC-70200"})  # noqa: E731
    client = SimulatorClient(Settings(), transport=httpx.MockTransport(sim_escalation))
    browser = CallSession(CALL, helpline="1800 210 4455")
    out = run(client, browser, "escalate_to_human", {"trigger": "SENSITIVE", "reason": "fraud", "summary": "unauthorised debit"})
    assert out["handoff"] == {"mode": "CALLBACK", "helpline": "1800 210 4455"} and browser.refs == ["ESC-70200"]
    phone = CallSession(CALL, phone_call_sid="CA123", transfer_to="+919800000000")
    assert run(client, phone, "escalate_to_human", {"trigger": "DISSATISFIED", "reason": "unhappy", "summary": "s"})["handoff"] == {"mode": "TRANSFER"}


def test_a_phone_call_with_no_human_agent_number_gets_a_call_back():
    client = SimulatorClient(Settings(), transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"ref": "ESC-70201"})))
    phone = CallSession(CALL, phone_call_sid="CA123", transfer_to=None, helpline="1800 210 4455")
    out = run(client, phone, "escalate_to_human", {"trigger": "SENSITIVE", "reason": "fraud", "summary": "s"})
    assert out["handoff"] == {"mode": "CALLBACK", "helpline": "1800 210 4455"}


def test_verify_sends_the_caller_ref_on_phone_calls_only():
    sim, client, call = setup()
    verify(client, call)
    assert "caller_ref" not in json.loads(sim.requests[-1].content)
    sim, client, _ = setup()
    verify(client, CallSession(CALL, caller_ref="+15005550199", spoke_numbers=True))
    assert json.loads(sim.requests[-1].content)["caller_ref"] == "+15005550199"


def test_verify_without_real_details_spends_no_attempt():
    sim, client, call = setup()
    for args in ({}, {"mobile": "", "date_of_birth": ""}, {"mobile": "98765", "date_of_birth": "1985-11-03"},
                 {"mobile": "9876500002", "date_of_birth": "third November"}):
        assert run(client, call, "verify_customer", args)["error"] == "MISSING_DETAILS"
    assert sim.requests == [] and call.verify_failures == 0


def test_a_named_loan_comes_back_only_if_it_is_the_callers():
    sim, client, call = setup()
    verify(client, call)
    assert [x["loan_id"] for x in run(client, call, "get_loans", {"loan_id": "vl-31003"})["items"]] == ["VL-31003"]
    other = run(client, call, "get_loans", {"loan_id": "VL-31007"})
    assert other["error"] == "NOT_YOUR_RECORD" and "items" not in other


def test_get_loans_accepts_null_for_its_optional_filters():  # Groq rejects a tool call whose null doesn't match the schema
    props = next(t for t in SUPPORT_TOOL_SCHEMAS if t["function"]["name"] == "get_loans")["function"]["parameters"]["properties"]
    assert all("null" in p["type"] for p in props.values()) and None in props["product_type"]["enum"]
    sim, client, call = setup()
    verify(client, call)
    assert len(run(client, call, "get_loans", {"product_type": None, "loan_id": None})["items"]) == 2


def test_asking_for_a_person_after_an_escalation_gets_the_same_reference_not_ask_first():
    sim, client, call = setup()
    first = run(client, call, "escalate_to_human", {"trigger": "SENSITIVE", "reason": "fraud", "summary": "unauthorised payment"})
    again = run(client, call, "escalate_to_human", {"trigger": "CUSTOMER_REQUEST", "reason": "wants a person", "summary": "s"})
    assert first["ref"] == again["ref"] == "ESC-70200" and again["escalated"] is True and "error" not in again
    assert call.refs == ["ESC-70200"] and sum(r.url.path == "/v1/csm/escalations" for r in sim.requests) == 1


def test_a_complaint_reference_is_looked_up_as_a_complaint_and_a_request_shows_its_loan():
    sim, client, call = setup()
    verify(client, call)
    complaint = run(client, call, "get_ticket", {"ref": " cmp-50011 "})
    assert complaint["ref"] == "CMP-50011" and complaint["status"] == "OPEN"
    assert sim.requests[-1].url.path == "/v1/csm/complaints/CMP-50011"
    request = run(client, call, "get_ticket", {"ref": "SR-40200"})
    assert request["details"]["loan_id"] == "VL-31003"
    assert sim.requests[-1].url.path == "/v1/csm/tickets/SR-40200"
    loan = run(client, call, "get_loans", {"loan_id": request["details"]["loan_id"]})
    assert [l["loan_id"] for l in loan["items"]] == ["VL-31003"]


def test_prompt_lists_every_record_and_follows_a_reference_to_its_loan():
    from app.support_prompt import support_prompt
    p = support_prompt()
    assert "SEVERAL RECORDS" in p and "how many there are" in p
    assert "get_ticket" in p and "loan_id" in p and "CMP-50011" in p
    assert "only when the caller says they have nothing else" in p
