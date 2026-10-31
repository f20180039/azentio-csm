"""The front-desk agent's tools. Personal tools refuse here, before any HTTP call, when the caller is not verified; the
simulator enforces the same rule again, so a prompt-injected tool call still gets nothing."""
import re
from dataclasses import dataclass, field
from enum import StrEnum

from .api_client import ApiUnavailable
from .simulator_client import SimulatorClient
from .spoken import spoken_inr
from .vocab import EscalationTrigger, HandoffMode, SupportTool, ToolError

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
    human_requests: int = 0
    phone_call_sid: str | None = None  # set on phone calls, so an escalation can transfer the live call
    transfer_to: str | None = None  # the person a live phone call is transferred to; None means a call-back
    caller_ref: str | None = None  # the caller's phone number on phone calls: the simulator's per-caller lock key
    helpline: str = ""

    @property
    def verified(self) -> bool:
        return self.session is not None


NOT_VERIFIED = {"error": ToolError.NOT_VERIFIED, "note": "Ask for the registered mobile number and date of birth first, then call verify_customer."}


def _tool(name: SupportTool, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name.value, "description": description,
                                             "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


def _enum(values: type[StrEnum], description: str) -> dict:
    return {"type": "string", "enum": [v.value for v in values], "description": description}


SUPPORT_TOOL_SCHEMAS: list[dict] = [
    _tool(SupportTool.VERIFY_CUSTOMER, "Verify the caller with their registered 10-digit mobile number and date of birth. Required before any personal tool.",
          {"mobile": {"type": "string", "description": "10-digit mobile number, digits only"},
           "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"}}, ["mobile", "date_of_birth"]),
    _tool(SupportTool.GET_LOAN_APPLICATIONS, "The verified caller's loan applications and their current stage."),
    _tool(SupportTool.GET_LOANS, "The verified caller's loan accounts: next instalment, overdue amount, outstanding principal.",
          {"product_type": {"type": ["string", "null"], "enum": ["personal", "vehicle", "home", None], "description": "Filter by loan type when the caller names one"},
           "loan_id": {"type": ["string", "null"], "description": "The loan reference when the caller names one, e.g. VL-31003; the bank checks it is theirs"}}),
    _tool(SupportTool.GET_SCHEDULE, "Repayment schedule of one of the caller's loans.", {"loan_id": {"type": "string"}}, ["loan_id"]),
    _tool(SupportTool.GET_ACCOUNTS, "The verified caller's bank accounts and balances."),
    _tool(SupportTool.GET_TRANSACTIONS, "Recent transactions; filter by status or by a transaction reference the caller gives.",
          {"status": {"type": "string", "enum": ["POSTED", "PENDING", "FAILED"]}, "ref": {"type": "string"}}),
    _tool(SupportTool.GET_TICKETS, "The verified caller's existing service requests."),
    _tool(SupportTool.GET_TICKET, "Status of one service request by its reference, e.g. SR-40102.", {"ref": {"type": "string"}}, ["ref"]),
    _tool(SupportTool.CREATE_SERVICE_REQUEST, "Raise a service request (statement, repayment schedule, document, address change) and get its reference.",
          {"category": _enum(TicketCategory, "Request type"), "summary": {"type": "string", "description": "One line: what the caller asked for"},
           "details": {"type": "object", "description": "Key details collected, e.g. loan_id, period, delivery"}}, ["category", "summary"]),
    _tool(SupportTool.REGISTER_COMPLAINT, "Record a complaint (failed transaction, incorrect charge, unauthorised transaction, poor service) and get its reference.",
          {"category": _enum(ComplaintCategory, "Complaint type"), "description": {"type": "string"},
           "severity": _enum(Severity, "HIGH for fraud, unauthorised debits or large losses")}, ["category", "description", "severity"]),
    _tool(SupportTool.GET_POLICIES, "The verified caller's insurance policies, premium due dates and coverage status."),
    _tool(SupportTool.GET_CLAIMS, "The verified caller's insurance claims and their status."),
    _tool(SupportTool.SEARCH_FAQ, "Search the bank's approved product and service answers. Use for general questions; no verification needed.",
          {"query": {"type": "string"}}, ["query"]),
    _tool(SupportTool.ROUTE_UNSUPPORTED, "Log a question the desk cannot answer or may not do, so the right team follows up. Use after politely declining.",
          {"query_text": {"type": "string", "description": "The caller's request in their words"}, "reason": {"type": "string"}},
          ["query_text", "reason"]),
    _tool(SupportTool.ESCALATE_TO_HUMAN,
          "Hand the caller to a human representative. Use trigger SENSITIVE at once for fraud, unauthorised transactions or distress; "
          "DISSATISFIED when the caller is unhappy with the help; UNRESOLVED when you could not answer or do what they need; "
          "CUSTOMER_REQUEST when they ask for a person (first ask what they need and try to help: the first such request is refused).",
          {"trigger": _enum(EscalationTrigger, "Why a person is needed"), "reason": {"type": "string"},
           "summary": {"type": "string", "description": "What the caller needs, for the human"}}, ["trigger", "reason", "summary"]),
    _tool(SupportTool.RECORD_RATING, "Record the caller's 1-5 rating of this call, and any comment, after you asked for it.",
          {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "comment": {"type": "string", "description": "What they said about the call, if anything"}},
          ["score"]),
    _tool(SupportTool.END_CALL, "End the call after saying goodbye."),
]

PERSONAL = frozenset({SupportTool.GET_LOAN_APPLICATIONS, SupportTool.GET_LOANS, SupportTool.GET_SCHEDULE, SupportTool.GET_ACCOUNTS,
                      SupportTool.GET_TRANSACTIONS, SupportTool.GET_TICKETS, SupportTool.GET_TICKET, SupportTool.CREATE_SERVICE_REQUEST,
                      SupportTool.REGISTER_COMPLAINT, SupportTool.GET_POLICIES, SupportTool.GET_CLAIMS})
REF_RAISING = frozenset({SupportTool.CREATE_SERVICE_REQUEST, SupportTool.REGISTER_COMPLAINT, SupportTool.ROUTE_UNSUPPORTED,
                         SupportTool.ESCALATE_TO_HUMAN})


def digits(text: str) -> str:
    d = "".join(c for c in str(text) if c.isdigit())
    return d[-10:] if len(d) >= 10 else d


async def run_support_tool(client: SimulatorClient, call: CallSession, name: str, args: dict) -> dict:
    """Never raises: a down simulator or bad arguments come back as {"error": ...} for the agent to explain."""
    try:
        if name in PERSONAL and call.locked:
            return {"error": ToolError.LOCKED, "note": "Verification is locked after repeated failures. Offer a human representative; share nothing."}
        if name in PERSONAL and not call.verified:
            return NOT_VERIFIED
        result = await _dispatch(client, call, name, args)
    except ApiUnavailable:
        return {"error": ToolError.SYSTEM_UNAVAILABLE, "note": "Say the system is unavailable right now and offer to raise a callback."}
    except (KeyError, TypeError, ValueError) as e:
        return {"error": ToolError.BAD_ARGUMENTS, "detail": f"{type(e).__name__}: {e}"[:200]}
    if result.get("error") == ToolError.NOT_YOUR_RECORD:
        result = {**result, "note": "That record belongs to someone else. Decline, and disclose nothing about it."}
    if result.get("error") == ToolError.NOT_VERIFIED:
        call.session = None
    ref = result.get("ref")
    if isinstance(ref, str) and name in REF_RAISING:
        call.refs.append(ref)
    return with_spoken(result)


async def _dispatch(client: SimulatorClient, call: CallSession, name: str, args: dict) -> dict:
    s = call.session
    match name:
        case SupportTool.VERIFY_CUSTOMER:
            mobile, dob = digits(args.get("mobile") or ""), str(args.get("date_of_birth") or "")
            if len(mobile) != 10 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):  # never spend an attempt on details not given
                return {**NOT_VERIFIED, "note": "Ask the caller for their registered 10-digit mobile number and date of birth; "
                                                "call verify_customer only with what they actually said."}
            out = await client.verify(mobile, dob, call.call_id, call.caller_ref)
            if "session" in out:
                call.session, call.customer, call.locked = out["session"], out.get("customer"), False
                return {"verified": True, "customer": out.get("customer")}
            if out.get("error") == ToolError.LOCKED:
                call.locked = True
            else:
                call.verify_failures += 1
                if out.get("attempts_left") == 0:  # the third failure locks; don't wait for a fourth try to find out
                    call.locked = True
                    out = {**out, "error": ToolError.LOCKED, "note": "Verification is now locked. Share nothing personal; offer a human representative."}
            return out
        case SupportTool.GET_LOAN_APPLICATIONS:
            return await client.applications(s)
        case SupportTool.GET_LOANS:
            out = await client.loans(s, args.get("product_type"))
            if not (loan_id := str(args.get("loan_id") or "").strip().upper()) or "error" in out:
                return out
            mine = [l for l in out.get("items", []) if l.get("loan_id") == loan_id]
            return {**out, "items": mine} if mine else await client.schedule(s, loan_id)  # not theirs: the bank's own refusal
        case SupportTool.GET_SCHEDULE:
            return await client.schedule(s, args["loan_id"])
        case SupportTool.GET_ACCOUNTS:
            return await client.accounts(s)
        case SupportTool.GET_TRANSACTIONS:
            return await client.transactions(s, args.get("status"), args.get("ref"))
        case SupportTool.GET_TICKETS:
            return await client.tickets(s)
        case SupportTool.GET_TICKET:
            return await client.ticket(s, args["ref"].strip().upper())
        case SupportTool.CREATE_SERVICE_REQUEST:
            return await client.create_ticket(s, TicketCategory(args["category"]), args["summary"], args.get("details") or {}, call.call_id)
        case SupportTool.REGISTER_COMPLAINT:
            return await client.complaint(s, ComplaintCategory(args["category"]), args["description"],
                                          Severity(args.get("severity") or "MEDIUM"), call.call_id)
        case SupportTool.GET_POLICIES:
            return await client.policies(s)
        case SupportTool.GET_CLAIMS:
            return await client.claims(s)
        case SupportTool.SEARCH_FAQ:
            out = await client.faq(args["query"])
            return out if out.get("items") else {"no_approved_answer": True,
                                                 "note": "No approved answer. Say so, do not improvise; offer to route the question."}
        case SupportTool.ROUTE_UNSUPPORTED:
            customer_ref = (call.customer or {}).get("customer_ref")
            return await client.routed(args["query_text"], args["reason"], call.call_id, customer_ref)
        case SupportTool.ESCALATE_TO_HUMAN:
            trigger = EscalationTrigger(args.get("trigger") or EscalationTrigger.CUSTOMER_REQUEST)
            if trigger == EscalationTrigger.CUSTOMER_REQUEST:
                call.human_requests += 1
                if call.human_requests == 1:
                    return {"error": ToolError.ASK_FIRST,
                            "note": "Not yet. Tell them you can help with most things, ask what they need, and try. "
                                    "If they ask for a person again, or you cannot help, call escalate_to_human again."}
            out = await client.escalation(s, f"{trigger}: {args['reason']}", args.get("summary") or args["reason"], call.call_id)
            if "error" in out:
                return out
            if call.phone_call_sid and call.transfer_to:
                return {**out, "handoff": {"mode": HandoffMode.TRANSFER},
                        "note": "Tell them you are connecting them to a colleague now, then stop talking."}
            return {**out, "handoff": {"mode": HandoffMode.CALLBACK, "helpline": call.helpline},
                    "note": "Tell them a colleague will call back, read the reference, and give the helpline number."}
        case SupportTool.END_CALL:
            return {"ended": True}
        case _:
            return {"error": ToolError.UNKNOWN_TOOL}


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
