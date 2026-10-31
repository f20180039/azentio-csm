"""The front-desk agent's tools. Personal tools refuse here, before any HTTP call, when the caller is not verified; the
simulator enforces the same rule again, so a prompt-injected tool call still gets nothing."""
from dataclasses import dataclass, field
from enum import StrEnum

from .api_client import ApiUnavailable
from .simulator_client import SimulatorClient
from .spoken import spoken_inr

AMOUNT_KEYS = {"amount", "balance", "outstanding_principal", "premium", "sum_insured", "amount_claimed", "amount_approved"}


class TicketCategory(StrEnum):
    STATEMENT = "STATEMENT"
    REPAYMENT_SCHEDULE = "REPAYMENT_SCHEDULE"
    ACCOUNT_DOCUMENT = "ACCOUNT_DOCUMENT"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"
    OTHER = "OTHER"


class ComplaintCategory(StrEnum):
    FAILED_TRANSACTION = "FAILED_TRANSACTION"
    INCORRECT_CHARGE = "INCORRECT_CHARGE"
    UNAUTHORISED_TRANSACTION = "UNAUTHORISED_TRANSACTION"
    SERVICE_EXPERIENCE = "SERVICE_EXPERIENCE"
    OTHER = "OTHER"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class CallSession:
    """What the agent knows about the caller during one call."""
    call_id: str
    session: str | None = None
    customer: dict | None = None
    verify_failures: int = 0
    locked: bool = False
    refs: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.session is not None


NOT_VERIFIED = {"error": "NOT_VERIFIED", "note": "Ask for the registered mobile number and date of birth first, then call verify_customer."}


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


def _enum(values: type[StrEnum], description: str) -> dict:
    return {"type": "string", "enum": [v.value for v in values], "description": description}


SUPPORT_TOOL_SCHEMAS: list[dict] = [
    _tool("verify_customer", "Verify the caller with their registered 10-digit mobile number and date of birth. Required before any personal tool.",
          {"mobile": {"type": "string", "description": "10-digit mobile number, digits only"},
           "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"}}, ["mobile", "date_of_birth"]),
    _tool("get_loan_applications", "The verified caller's loan applications and their current stage."),
    _tool("get_loans", "The verified caller's loan accounts: next instalment, overdue amount, outstanding principal.",
          {"product_type": {"type": "string", "enum": ["personal", "vehicle", "home"], "description": "Filter by loan type when the caller names one"}}),
    _tool("get_schedule", "Repayment schedule of one of the caller's loans.", {"loan_id": {"type": "string"}}, ["loan_id"]),
    _tool("get_accounts", "The verified caller's bank accounts and balances."),
    _tool("get_transactions", "Recent transactions; filter by status or by a transaction reference the caller gives.",
          {"status": {"type": "string", "enum": ["POSTED", "PENDING", "FAILED"]}, "ref": {"type": "string"}}),
    _tool("get_tickets", "The verified caller's existing service requests."),
    _tool("get_ticket", "Status of one service request by its reference, e.g. SR-40102.", {"ref": {"type": "string"}}, ["ref"]),
    _tool("create_service_request", "Raise a service request (statement, repayment schedule, document, address change) and get its reference.",
          {"category": _enum(TicketCategory, "Request type"), "summary": {"type": "string", "description": "One line: what the caller asked for"},
           "details": {"type": "object", "description": "Key details collected, e.g. loan_id, period, delivery"}}, ["category", "summary"]),
    _tool("register_complaint", "Record a complaint (failed transaction, incorrect charge, unauthorised transaction, poor service) and get its reference.",
          {"category": _enum(ComplaintCategory, "Complaint type"), "description": {"type": "string"},
           "severity": _enum(Severity, "HIGH for fraud, unauthorised debits or large losses")}, ["category", "description", "severity"]),
    _tool("get_policies", "The verified caller's insurance policies, premium due dates and coverage status."),
    _tool("get_claims", "The verified caller's insurance claims and their status."),
    _tool("search_faq", "Search the bank's approved product and service answers. Use for general questions; no verification needed.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("route_unsupported", "Log a question the desk cannot answer or may not do, so the right team follows up. Use after politely declining.",
          {"query_text": {"type": "string", "description": "The caller's request in their words"}, "reason": {"type": "string"}},
          ["query_text", "reason"]),
    _tool("escalate_to_human", "Hand the call to a human representative: fraud, unauthorised transactions, distress, repeated failure, or on request.",
          {"reason": {"type": "string"}, "summary": {"type": "string", "description": "What the caller needs, for the human"}}, ["reason", "summary"]),
    _tool("end_call", "End the call after saying goodbye."),
]

PERSONAL = {"get_loan_applications", "get_loans", "get_schedule", "get_accounts", "get_transactions", "get_tickets", "get_ticket",
            "create_service_request", "register_complaint", "get_policies", "get_claims"}


def digits(text: str) -> str:
    d = "".join(c for c in str(text) if c.isdigit())
    return d[-10:] if len(d) >= 10 else d


async def run_support_tool(client: SimulatorClient, call: CallSession, name: str, args: dict) -> dict:
    """Never raises: a down simulator or bad arguments come back as {"error": ...} for the agent to explain."""
    try:
        if name in PERSONAL and call.locked:
            return {"error": "LOCKED", "note": "Verification is locked after repeated failures. Offer a human representative; share nothing."}
        if name in PERSONAL and not call.verified:
            return NOT_VERIFIED
        result = await _dispatch(client, call, name, args)
    except ApiUnavailable:
        return {"error": "SYSTEM_UNAVAILABLE", "note": "Say the system is unavailable right now and offer to raise a callback."}
    except (KeyError, TypeError, ValueError) as e:
        return {"error": "BAD_ARGUMENTS", "detail": f"{type(e).__name__}: {e}"[:200]}
    if result.get("error") == "NOT_YOUR_RECORD":
        result = {**result, "note": "That record belongs to someone else. Decline, and disclose nothing about it."}
    if result.get("error") == "NOT_VERIFIED":
        call.session = None
    ref = result.get("ref")
    if isinstance(ref, str) and name in {"create_service_request", "register_complaint", "route_unsupported", "escalate_to_human"}:
        call.refs.append(ref)
    return with_spoken(result)


async def _dispatch(client: SimulatorClient, call: CallSession, name: str, args: dict) -> dict:
    s = call.session
    match name:
        case "verify_customer":
            out = await client.verify(digits(args["mobile"]), args["date_of_birth"], call.call_id)
            if "session" in out:
                call.session, call.customer, call.locked = out["session"], out.get("customer"), False
                return {"verified": True, "customer": out.get("customer")}
            if out.get("error") == "LOCKED":
                call.locked = True
            else:
                call.verify_failures += 1
                if out.get("attempts_left") == 0:  # the third failure locks; don't wait for a fourth try to find out
                    call.locked = True
                    out = {**out, "error": "LOCKED", "note": "Verification is now locked. Share nothing personal; offer a human representative."}
            return out
        case "get_loan_applications":
            return await client.applications(s)
        case "get_loans":
            return await client.loans(s, args.get("product_type"))
        case "get_schedule":
            return await client.schedule(s, args["loan_id"])
        case "get_accounts":
            return await client.accounts(s)
        case "get_transactions":
            return await client.transactions(s, args.get("status"), args.get("ref"))
        case "get_tickets":
            return await client.tickets(s)
        case "get_ticket":
            return await client.ticket(s, args["ref"].strip().upper())
        case "create_service_request":
            return await client.create_ticket(s, TicketCategory(args["category"]), args["summary"], args.get("details") or {}, call.call_id)
        case "register_complaint":
            return await client.complaint(s, ComplaintCategory(args["category"]), args["description"],
                                          Severity(args.get("severity") or "MEDIUM"), call.call_id)
        case "get_policies":
            return await client.policies(s)
        case "get_claims":
            return await client.claims(s)
        case "search_faq":
            out = await client.faq(args["query"])
            return out if out.get("items") else {"no_approved_answer": True,
                                                 "note": "No approved answer. Say so, do not improvise; offer to route the question."}
        case "route_unsupported":
            customer_ref = (call.customer or {}).get("customer_ref")
            return await client.routed(args["query_text"], args["reason"], call.call_id, customer_ref)
        case "escalate_to_human":
            return await client.escalation(s, args["reason"], args.get("summary") or args["reason"], call.call_id)
        case "end_call":
            return {"ended": True}
        case _:
            return {"error": "UNKNOWN_TOOL"}


def with_spoken(value):
    """Adds a spoken form next to every rupee amount, so the agent reads figures exactly as stored."""
    if isinstance(value, list):
        return [with_spoken(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {k: with_spoken(v) for k, v in value.items()}
    for k, v in value.items():
        if k in AMOUNT_KEYS and isinstance(v, int) and not isinstance(v, bool):
            out[f"{k}_spoken"] = spoken_inr(v)
    return out
