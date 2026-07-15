"""Values used by transaction models."""

from enum import StrEnum


class TransactionType(StrEnum):
    """Supported transfer types."""

    INTERNAL_TRANSFER = "internal_transfer"
    EXTERNAL_TRANSFER = "external_transfer"


class TransactionStatus(StrEnum):
    """Lifecycle states of a transaction."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
