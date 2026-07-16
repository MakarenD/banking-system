"""Audit and risk analysis models."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

from .enums import AuditLevel, RiskFactor, RiskLevel


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """A single immutable audit event."""

    timestamp: datetime
    level: AuditLevel
    event_type: str
    message: str
    transaction_id: str | None = None
    account_number: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of the record."""

        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "event_type": self.event_type,
            "message": self.message,
            "transaction_id": self.transaction_id,
            "account_number": self.account_number,
            "details": _json_compatible(dict(self.details)),
        }


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Risk signals calculated for one transaction."""

    transaction_id: str
    account_number: str
    recipient_account_number: str
    timestamp: datetime
    level: RiskLevel
    factors: tuple[RiskFactor, ...]
    score: int


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, datetime, Enum)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Audit details must contain finite numbers")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Audit details must contain finite numbers")
        return value
    raise TypeError("Audit details must contain JSON-compatible values")
