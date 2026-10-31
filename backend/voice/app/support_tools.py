"""The front-desk agent's tools. Personal tools refuse here, before any HTTP call, when the caller is not verified; the
simulator enforces the same rule again, so a prompt-injected tool call still gets nothing."""
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .api_client import ApiUnavailable
from .identity import MOBILE_LEN, clean_dob, clean_mobile
from .simulator_client import SimulatorClient
from .spoken import spoken_inr
from .vocab import OFFERED_TRIGGERS, EscalationTrigger, HandoffMode, RefPrefix, SupportTool, ToolError, VerifyField, VerifyMismatch

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
    heard_mobile: str | None = None  # the mobile number the caller themselves said, latest wins
    heard_dob: str | None = None  # the date of birth the caller themselves said, ISO, latest wins
    heard_digits: str | None = None  # the last run of digits that was an attempt at a mobile number but not 10 digits long
    model_may_fill: set[VerifyField] = field(default_factory=set)  # fields the model's own value may stand in for: a caller turn
    # carried numbers this code could not read (Kannada or Hindi number words, a two-digit year); a bank mismatch takes the field out again
    today: date = field(default_factory=date.today)  # for judging a date of birth; fixed in tests
    last_caller_text: str = ""  # the caller's latest words, kept verbatim on a complaint as its original_statement

    @property
    def verified(self) -> bool:
        return self.session is not None


NOT_VERIFIED = {"error": ToolError.NOT_VERIFIED, "note": "Ask for the registered mobile number and date of birth first, then call verify_customer."}
ASK_BOTH = "Ask for the registered mobile number and date of birth."
ASK_MOBILE_ONLY = "Ask only for the registered 10-digit mobile number; the date of birth is already noted."
ASK_DOB_ONLY = "Ask only for the date of birth; the mobile number is already noted."
CONFIRM_BOTH = ("The details do not match our records. Ask the caller to confirm both their mobile number and date of birth. "
                "Do not say which one is wrong.")
MISMATCH_NOTES = {
    VerifyMismatch.MOBILE_NOT_FOUND: ("That mobile number is not registered with us. Ask only for the registered mobile number; "
                                      "keep the date of birth. This is the last attempt."),
    VerifyMismatch.DOB_MISMATCH: ("The date of birth does not match the mobile number. Ask only for the date of birth; "
                                  "keep the mobile number. This is the last attempt."),
}


def _tool(name: SupportTool, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name.value, "description": description,
                                             "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


def _enum(values: type[StrEnum] | tuple[StrEnum, ...], description: str) -> dict:
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
    _tool(SupportTool.GET_TICKET, "Status of one service request or complaint by its reference, e.g. SR-40102 or CMP-50011. "
          "A request's details name what it is about, e.g. its loan_id.", {"ref": {"type": "string"}}, ["ref"]),
    _tool(SupportTool.CREATE_SERVICE_REQUEST, "Raise a service request (statement, repayment schedule, document, address change) and get its reference.",
          {"category": _enum(TicketCategory, "Request type"), "summary": {"type": "string", "description": "One line: what the caller asked for"},
           "details": {"type": "object", "description": "Key details collected, e.g. loan_id, period, delivery"}}, ["category", "summary"]),
    _tool(SupportTool.REGISTER_COMPLAINT, "Record a complaint (failed transaction, incorrect charge, unauthorised transaction, poor service) and get its reference.",
          {"category": _enum(ComplaintCategory, "Complaint type"), "description": {"type": "string"},
           "severity": _enum(Severity, "HIGH for fraud, unauthorised debits or large losses"),
           "related_ref": {"type": "string", "description": "Account, loan or transaction reference the complaint is about, e.g. TXN-88213"}},
          ["category", "description", "severity"]),
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
          {"trigger": _enum(OFFERED_TRIGGERS, "Why a person is needed"), "reason": {"type": "string"},
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


def resolve_identity(call: CallSession, args: dict) -> tuple[str | None, str | None]:
    """The mobile and date of birth to verify with: what the caller said wins; the model's value counts only when it is
    well-formed and a caller turn carried numbers this code could not read (Kannada or Hindi number words)."""
    mobile = call.heard_mobile or (clean_mobile(args.get("mobile") or "") if VerifyField.MOBILE in call.model_may_fill else None)
    dob = call.heard_dob or (clean_dob(args.get("date_of_birth") or "", call.today) if VerifyField.DOB in call.model_may_fill else None)
    return mobile, dob


def missing_details(call: CallSession, mobile: str | None, dob: str | None) -> dict | None:
    have = [f for f, v in ((VerifyField.MOBILE, mobile), (VerifyField.DOB, dob)) if v]
    missing = [f for f in VerifyField if f not in have]
    if not missing:
        return None
    if missing == [VerifyField.MOBILE]:
        note = ASK_MOBILE_ONLY
        if call.heard_digits and len(call.heard_digits) != MOBILE_LEN:
            note += f" The number heard had {len(call.heard_digits)} digits."
    else:
        note = ASK_DOB_ONLY if missing == [VerifyField.DOB] else ASK_BOTH
    return {"error": ToolError.MISSING_DETAILS, "missing": missing, "have": have, "note": note}


def apply_mismatch(call: CallSession, mismatch: str | None) -> str:
    """The note for a failed attempt, and what it does to the call. After the first: confirm both, naming neither. After the
    second: name the wrong field, forget everything heard for it, and keep the other; the model may not refill it from its own
    copy, only a fresh caller turn can. An unknown reason keeps the cautious wording."""
    if call.verify_failures < 2 or mismatch not in MISMATCH_NOTES:
        return CONFIRM_BOTH
    if mismatch == VerifyMismatch.MOBILE_NOT_FOUND:
        call.heard_mobile, call.heard_digits = None, None
        call.model_may_fill.discard(VerifyField.MOBILE)
    else:
        call.heard_dob = None
        call.model_may_fill.discard(VerifyField.DOB)
    return MISMATCH_NOTES[VerifyMismatch(mismatch)]


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
    if isinstance(ref, str) and name in REF_RAISING and ref not in call.refs:
        call.refs.append(ref)
    return with_spoken(result)


async def _dispatch(client: SimulatorClient, call: CallSession, name: str, args: dict) -> dict:
    s = call.session
    match name:
        case SupportTool.VERIFY_CUSTOMER:
            mobile, dob = resolve_identity(call, args)
            if missing := missing_details(call, mobile, dob):  # never spend an attempt on details the caller has not given
                return missing
            out = await client.verify(mobile, dob, call.call_id, call.caller_ref)
            if "session" in out:
                call.session, call.customer, call.locked = out["session"], out.get("customer"), False
                return {"verified": True, "customer": out.get("customer")}
            mismatch = out.pop("mismatch", None)  # the bank's reason is for apply_mismatch only: the model sees just the note
            if out.get("error") == ToolError.LOCKED:
                call.locked = True
            else:
                call.verify_failures += 1
                if out.get("attempts_left") == 0:  # the third failure locks; don't wait for a fourth try to find out
                    call.locked = True
                    out = {**out, "error": ToolError.LOCKED, "note": "Verification is now locked. Share nothing personal; offer a human representative."}
                else:
                    out = {**out, "note": apply_mismatch(call, mismatch)}
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
            ref = args["ref"].strip().upper()
            return await (client.complaint_status(s, ref) if ref.startswith(RefPrefix.COMPLAINT) else client.ticket(s, ref))
        case SupportTool.CREATE_SERVICE_REQUEST:
            return await client.create_ticket(s, TicketCategory(args["category"]), args["summary"], args.get("details") or {}, call.call_id)
        case SupportTool.REGISTER_COMPLAINT:
            related_ref = str(args.get("related_ref") or "").strip().upper() or None
            return await client.complaint(s, ComplaintCategory(args["category"]), args["description"],
                                          Severity(args.get("severity") or "MEDIUM"), call.call_id,
                                          original_statement=call.last_caller_text or None, related_ref=related_ref)
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
            if earlier := next((r for r in call.refs if r.startswith(RefPrefix.ESCALATION)), None):
                return {"escalated": True, "ref": earlier, "already_escalated": True,
                        "note": "This call is already with a person: give the same reference and say a colleague will be in touch."}
            if trigger == EscalationTrigger.CUSTOMER_REQUEST:
                call.human_requests += 1
                if call.human_requests == 1:
                    return {"error": ToolError.ASK_FIRST,
                            "note": "Not yet. Tell them you can help with most things, ask what they need, and try. "
                                    "If they ask for a person again, or you cannot help, call escalate_to_human again."}
            out = await client.escalation(s, f"{trigger}: {args['reason']}", args.get("summary") or args["reason"], call.call_id,
                                          category=trigger, related_refs=list(call.refs))
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
