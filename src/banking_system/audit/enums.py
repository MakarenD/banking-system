"""Values used by audit and risk analysis."""

from enum import StrEnum


class AuditLevel(StrEnum):
    """Importance of an audit record."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RiskFactor(StrEnum):
    """Signals that can increase transaction risk."""

    LARGE_AMOUNT = "large_amount"
    FREQUENT_OPERATIONS = "frequent_operations"
    NEW_RECIPIENT = "new_recipient"
    NIGHT_OPERATION = "night_operation"


class RiskLevel(StrEnum):
    """Resulting transaction risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
