"""Fixed vocabularies shared by the support agent, the voice service and the eval harness.

Every value is part of a wire contract (tool calls, Spring call records, the simulator, the operator panel), so the
values stay byte-identical; rename a member freely, never its value.

- SupportTool: names of the front-desk agent's tools, as the LLM calls them.
- ToolError: the "error" codes a tool result can carry back to the agent.
- Outcome: how a support call ended, as recorded in Spring.
- Channel: how a support call reached the desk, as recorded in Spring.
- TurnRole: who spoke a transcript turn.
- RefPrefix: reference prefixes of the records a call can raise (service request, complaint, routed query, escalation).
- IntentSource: which classifier produced a turn's intents.
- MetaKey: keys of the per-turn metadata written to Spring for the operator panel.
- Route: voice service endpoints that are named in more than one place (decorator, middleware allow-list, harness).
"""
from enum import StrEnum


class SupportTool(StrEnum):
    VERIFY_CUSTOMER = "verify_customer"
    GET_LOAN_APPLICATIONS = "get_loan_applications"
    GET_LOANS = "get_loans"
    GET_SCHEDULE = "get_schedule"
    GET_ACCOUNTS = "get_accounts"
    GET_TRANSACTIONS = "get_transactions"
    GET_TICKETS = "get_tickets"
    GET_TICKET = "get_ticket"
    CREATE_SERVICE_REQUEST = "create_service_request"
    REGISTER_COMPLAINT = "register_complaint"
    GET_POLICIES = "get_policies"
    GET_CLAIMS = "get_claims"
    SEARCH_FAQ = "search_faq"
    ROUTE_UNSUPPORTED = "route_unsupported"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    END_CALL = "end_call"
    RECORD_RATING = "record_rating"


class ToolError(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    LOCKED = "LOCKED"
    NOT_YOUR_RECORD = "NOT_YOUR_RECORD"
    SYSTEM_UNAVAILABLE = "SYSTEM_UNAVAILABLE"
    BAD_ARGUMENTS = "BAD_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ASK_FIRST = "ASK_FIRST"


class EscalationTrigger(StrEnum):
    """Why the agent hands a caller to a person. A bare request for a person is not enough on its own."""
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"  # the caller asked for a person (honoured on the second ask)
    DISSATISFIED = "DISSATISFIED"          # the caller is unhappy with the help so far
    UNRESOLVED = "UNRESOLVED"              # the agent could not answer or do what was needed
    SENSITIVE = "SENSITIVE"                # fraud, unauthorised transactions, distress: at once


class HandoffMode(StrEnum):
    TRANSFER = "TRANSFER"  # phone: the live call is dialled through to a person
    CALLBACK = "CALLBACK"  # browser: a person calls back; the helpline number is given


class Outcome(StrEnum):
    RESOLVED = "RESOLVED"
    TICKET_CREATED = "TICKET_CREATED"
    COMPLAINT_REGISTERED = "COMPLAINT_REGISTERED"
    ROUTED = "ROUTED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"


class Channel(StrEnum):
    VOICE = "VOICE"
    SIM_AUDIO = "SIM_AUDIO"
    TEXT = "TEXT"


class TurnRole(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"


class RefPrefix(StrEnum):
    SERVICE_REQUEST = "SR-"
    COMPLAINT = "CMP-"
    ROUTED = "RQ-"
    ESCALATION = "ESC-"


class IntentSource(StrEnum):
    LLM = "llm"
    RULES = "rules"


class MetaKey(StrEnum):
    INTENTS = "intents"
    INTENT_SOURCE = "intent_source"
    VERIFIED = "verified"
    VERIFY_FAILURES = "verify_failures"
    LOCKED = "locked"
    NO_SPEECH = "no_speech"
    REASON = "reason"
    GREETING = "greeting"
    TOOL_TRACE = "tool_trace"
    RETRIEVED = "retrieved"
    REFS = "refs"


class Route(StrEnum):
    SUPPORT_TEXT_CALL = "/support/text-call"
    SUPPORT_TEXT_TURN = "/support/text-turn"
    SUPPORT_END = "/support/end"
    SUPPORT_OFFER = "/support/offer"
    SIM_AUDIO = "/sim/audio"
    HEALTH = "/health"
    API_OFFER = "/api/offer"
    TWILIO_TWIML = "/twilio/twiml"
    TWILIO_WS = "/ws/twilio"
