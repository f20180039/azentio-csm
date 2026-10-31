"""Route paths, defined once."""
from enum import StrEnum

API_PREFIX = "/api/v1"


class ApiPath(StrEnum):
    HEALTH = "/health"
    ME = "/me"
    PACKS = "/packs"
    STATS = "/stats"
    AUDIT_VERIFY = "/audit/verify"

    RENEWALS = "/renewals"
    RENEWAL_QUEUE = "/queue"
    RENEWAL_DASHBOARD = "/dashboard"
    RENEWAL_CALLS = "/calls"
    RENEWAL_MARK_SIMULATED = "/calls/mark-simulated"
    RENEWAL_CALL = "/calls/{call_id}"
    RENEWAL_VERIFY = "/calls/{call_id}/verify"
    RENEWAL_POLICY = "/calls/{call_id}/policy"
    RENEWAL_OPTIONS = "/calls/{call_id}/options"
    RENEWAL_QUOTE = "/calls/{call_id}/quote"
    RENEWAL_PAYMENT_LINK = "/calls/{call_id}/payment-link"
    RENEWAL_HANDOFF = "/calls/{call_id}/handoff"
    RENEWAL_TURNS = "/calls/{call_id}/turns"
    RENEWAL_END = "/calls/{call_id}/end"

    SUPPORT_CALLS = "/support/calls"
    SUPPORT_CALL = "/{call_id}"
    SUPPORT_TURNS = "/{call_id}/turns"
    SUPPORT_TURN_META = "/{call_id}/turns/{seq}/meta"
    SUPPORT_END = "/{call_id}/end"
    SUPPORT_RATING = "/{call_id}/rating"
    SUPPORT_TURN_FEEDBACK = "/{call_id}/turns/{seq}/feedback"
    SUPPORT_TURN_TRANSCRIPT = "/{call_id}/turns/{seq}/transcript"

    SUPPORT = "/support"
    SUPPORT_REVIEW = "/review"
    SUPPORT_REVIEW_RESOLVE = "/review/{call_id}/resolve"
    SUPPORT_LESSONS = "/lessons"
    SUPPORT_LESSON = "/lessons/{lesson_id}"
    SUPPORT_INSIGHTS = "/insights"

    CASES = "/cases"
    CASE = "/{case_id}"
    CASE_DECISION = "/{case_id}/decision"
    CASE_AUDIT = "/{case_id}/audit"
