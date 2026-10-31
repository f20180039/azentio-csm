"""Domain enums matching the bank simulator shared contract."""
from enum import StrEnum


class Stage(StrEnum):
    SUBMITTED = "SUBMITTED"
    DOCUMENT_VERIFICATION = "DOCUMENT_VERIFICATION"
    CREDIT_REVIEW = "CREDIT_REVIEW"
    SANCTIONED = "SANCTIONED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"


class ProductType(StrEnum):
    PERSONAL = "personal"
    VEHICLE = "vehicle"
    HOME = "home"


class InstalmentStatus(StrEnum):
    PAID = "PAID"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    UPCOMING = "UPCOMING"


class Direction(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class TxnStatus(StrEnum):
    POSTED = "POSTED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class TicketCategory(StrEnum):
    STATEMENT = "STATEMENT"
    REPAYMENT_SCHEDULE = "REPAYMENT_SCHEDULE"
    ACCOUNT_DOCUMENT = "ACCOUNT_DOCUMENT"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"
    OTHER = "OTHER"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_INFO = "AWAITING_INFO"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Department(StrEnum):
    """The bank team a service request sits with."""
    ACCOUNT_SERVICES = "Account Services"
    LOAN_SERVICING = "Loan Servicing"
    KYC_RECORDS = "KYC & Records"
    CUSTOMER_SERVICE = "Customer Service"


TICKET_DEPARTMENT: dict[TicketCategory, Department] = {
    TicketCategory.STATEMENT: Department.ACCOUNT_SERVICES,
    TicketCategory.REPAYMENT_SCHEDULE: Department.LOAN_SERVICING,
    TicketCategory.ACCOUNT_DOCUMENT: Department.ACCOUNT_SERVICES,
    TicketCategory.ADDRESS_CHANGE: Department.KYC_RECORDS,
    TicketCategory.OTHER: Department.CUSTOMER_SERVICE,
}


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


class PolicyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"


class ClaimStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class ErrorCode(StrEnum):
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    LOCKED = "LOCKED"
    CALLER_BLOCKED = "CALLER_BLOCKED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_YOUR_RECORD = "NOT_YOUR_RECORD"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"


class VerifyOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    LOCKED = "LOCKED"
    CALLER_BLOCKED = "CALLER_BLOCKED"


class LockScope(StrEnum):
    CUSTOMER = "CUSTOMER"
    CALLER = "CALLER"


class EscalationCategory(StrEnum):
    SECURITY = "SECURITY"


class EscalationReason(StrEnum):
    CALLER_BLOCKED = "CALLER_BLOCKED"


class AuditAction(StrEnum):
    VERIFY_ATTEMPT = "VERIFY_ATTEMPT"


class RefPrefix(StrEnum):
    TICKET = "SR"
    COMPLAINT = "CMP"
    ROUTED = "RQ"
    ESCALATION = "ESC"


class RecordKind(StrEnum):
    TICKET = "ticket"
    COMPLAINT = "complaint"
    ROUTED = "routed"
    ESCALATION = "escalation"


class Route(StrEnum):
    """Endpoint paths, relative to API_PREFIX."""
    VERIFY = "/verify"
    LOS_APPLICATIONS = "/los/applications"
    LMS_LOANS = "/lms/loans"
    LMS_SCHEDULE = "/lms/loans/{loan_id}/schedule"
    CBS_ACCOUNTS = "/cbs/accounts"
    CBS_TRANSACTIONS = "/cbs/transactions"
    INSURANCE_POLICIES = "/insurance/policies"
    INSURANCE_CLAIMS = "/insurance/claims"
    CSM_TICKETS = "/csm/tickets"
    CSM_TICKET = "/csm/tickets/{ref}"
    CSM_COMPLAINTS = "/csm/complaints"
    CSM_ROUTED = "/csm/routed"
    CSM_ESCALATIONS = "/csm/escalations"
    FAQ_SEARCH = "/faq/search"
    OPS_RECORDS = "/ops/records"
    OPS_RESET = "/ops/reset"
    OPS_CUSTOMER = "/ops/customers/{customer_ref}"
    OPS_TICKET = "/ops/tickets/{ref}"


API_PREFIX = "/v1"
SESSION_HEADER = "X-Customer-Session"
