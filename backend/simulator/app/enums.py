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
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


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
