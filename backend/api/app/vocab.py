"""Every fixed vocabulary the API speaks, defined once (AGENTS.md: no repeated string literals)."""
from enum import StrEnum


class Role(StrEnum):
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"
    VOICE = "VOICE"


class CallKind(StrEnum):
    RENEWAL = "RENEWAL"
    SUPPORT = "SUPPORT"


class Channel(StrEnum):
    VOICE = "VOICE"
    SIM_AUDIO = "SIM_AUDIO"
    TEXT = "TEXT"
    PHONE = "PHONE"


class Outcome(StrEnum):
    """Support call outcomes (shared contract)."""
    RESOLVED = "RESOLVED"
    TICKET_CREATED = "TICKET_CREATED"
    COMPLAINT_REGISTERED = "COMPLAINT_REGISTERED"
    ROUTED = "ROUTED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"


class RenewalOutcome(StrEnum):
    HANDED_OFF = "HANDED_OFF"
    RENEWAL_PENDING_PAYMENT = "RENEWAL_PENDING_PAYMENT"
    NO_DECISION = "NO_DECISION"


class TurnRole(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"


class RatingSource(StrEnum):
    VOICE = "VOICE"
    PANEL = "PANEL"


class FeedbackVerdict(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"


class ReviewReason(StrEnum):
    LOW_RATING = "LOW_RATING"
    DISSATISFIED = "DISSATISFIED"
    BAD_FEEDBACK = "BAD_FEEDBACK"


class LessonStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SupportTool(StrEnum):
    """Voice-agent tool names read back from a turn's meta.tool_trace."""
    ESCALATE_TO_HUMAN = "escalate_to_human"


class EscalationTrigger(StrEnum):
    """The escalate_to_human trigger that puts a call in the review queue."""
    DISSATISFIED = "DISSATISFIED"


class CaseStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    AUTO_CLEARED = "AUTO_CLEARED"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


REVIEWABLE = frozenset({CaseStatus.NEEDS_REVIEW, CaseStatus.ESCALATED, CaseStatus.AUTO_CLEARED})


class CaseAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


CASE_ACTION_STATUS = {
    CaseAction.APPROVE: CaseStatus.APPROVED,
    CaseAction.REJECT: CaseStatus.REJECTED,
    CaseAction.ESCALATE: CaseStatus.ESCALATED,
}


class CaseType(StrEnum):
    RENEWAL_CALL = "renewal_call"
    SUPPORT_CALL = "support_call"


class Route(StrEnum):
    AGENT_CALL = "AGENT_CALL"
    HUMAN_ONLY = "HUMAN_ONLY"
    REMINDER_SMS = "REMINDER_SMS"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


SEVERITY_FACTOR = {Severity.LOW: 0.3, Severity.MEDIUM: 0.6, Severity.HIGH: 1.0}


class SignalCode(StrEnum):
    EXPIRY_7D = "EXPIRY_7D"
    EXPIRY_14D = "EXPIRY_14D"
    PREMIUM_UP_15 = "PREMIUM_UP_15"
    PREMIUM_UP_5 = "PREMIUM_UP_5"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    AUTODEBIT_FAILED = "AUTODEBIT_FAILED"
    REMINDERS_IGNORED = "REMINDERS_IGNORED"


class PaymentPlanInstalments(StrEnum):
    QUARTERLY = "quarterly"


class DeliveryChannel(StrEnum):
    SMS = "SMS"


class ErrorCode(StrEnum):
    """Machine-readable refusal codes, sent as the problem `detail`."""
    HUMAN_ONLY = "HUMAN_ONLY"
    DO_NOT_CALL = "DO_NOT_CALL"
    OUTSIDE_CALLING_HOURS = "OUTSIDE_CALLING_HOURS"
    VERIFY_LOCKED = "VERIFY_LOCKED"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"
    MUST_HANDOFF = "MUST_HANDOFF"
    OUTSIDE_PLAYBOOK = "OUTSIDE_PLAYBOOK"
    INVALID_OPTION = "INVALID_OPTION"
    STALE_QUOTE = "STALE_QUOTE"
    CALL_ENDED = "CALL_ENDED"
    CALL_ALREADY_ENDED = "CALL_ALREADY_ENDED"


class Tool(StrEnum):
    """Renewal tool names as recorded in `tool.refused` audit payloads."""
    VERIFY = "verify"
    GET_POLICY = "get_policy"
    LIST_ALLOWED_OPTIONS = "list_allowed_options"
    QUOTE_RENEWAL = "quote_renewal"
    SEND_PAYMENT_LINK = "send_payment_link"
    HANDOFF_TO_HUMAN = "handoff_to_human"
    TURN = "turn"


class AuditAction(StrEnum):
    API_BOOT = "api.boot"
    CALL_STARTED = "call.started"
    CALL_ENDED = "call.ended"
    IDENTITY_VERIFIED = "identity.verified"
    IDENTITY_FAILED = "identity.failed"
    TOOL_REFUSED = "tool.refused"
    TOOL_GET_POLICY = "tool.get_policy"
    TOOL_LIST_ALLOWED_OPTIONS = "tool.list_allowed_options"
    TOOL_QUOTE_RENEWAL = "tool.quote_renewal"
    TOOL_SEND_PAYMENT_LINK = "tool.send_payment_link"
    TOOL_HANDOFF_TO_HUMAN = "tool.handoff_to_human"
    RULE_OUTSIDE_PLAYBOOK = "rule.outside_playbook"
    CALLS_MARKED_SIMULATED = "calls.marked_simulated"
    CASE_APPROVE = "CASE_APPROVE"
    CASE_REJECT = "CASE_REJECT"
    CASE_ESCALATE = "CASE_ESCALATE"
    RATING_RECORDED = "rating.recorded"
    FEEDBACK_RECORDED = "feedback.recorded"
    REVIEW_RESOLVED = "review.resolved"
    LESSON_PROPOSED = "lesson.proposed"
    LESSON_STATUS_CHANGED = "lesson.status_changed"


CASE_DECISION_AUDIT = {
    CaseAction.APPROVE: AuditAction.CASE_APPROVE,
    CaseAction.REJECT: AuditAction.CASE_REJECT,
    CaseAction.ESCALATE: AuditAction.CASE_ESCALATE,
}

GUARDRAIL_ACTIONS = (
    AuditAction.RULE_OUTSIDE_PLAYBOOK,
    AuditAction.TOOL_REFUSED,
    AuditAction.IDENTITY_FAILED,
    AuditAction.TOOL_HANDOFF_TO_HUMAN,
)

SUMMARY_STATEMENTS = {
    AuditAction.TOOL_QUOTE_RENEWAL: "Agent quoted a renewal option within the playbook.",
    AuditAction.TOOL_SEND_PAYMENT_LINK: "Payment link sent to the customer's registered mobile.",
    AuditAction.RULE_OUTSIDE_PLAYBOOK: "Customer asked for a discount beyond the playbook limit.",
    AuditAction.TOOL_HANDOFF_TO_HUMAN: "Call handed to a human colleague.",
}


def sql_in(enum: type[StrEnum]) -> str:
    """A SQL value list for CHECK constraints, derived from the enum."""
    return ", ".join(f"'{v.value}'" for v in enum)
