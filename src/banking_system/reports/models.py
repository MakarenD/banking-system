"""Reporting models."""

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from banking_system.audit import RiskLevel

from .enums import ReportType


@dataclass(frozen=True, slots=True)
class Report:
    """A typed report envelope shared by every output format."""

    report_type: ReportType
    title: str
    generated_at: datetime
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.report_type, ReportType):
            raise TypeError("Report type must be a ReportType instance")
        if not isinstance(self.title, str):
            raise TypeError("Report title must be a string")
        if not self.title.strip():
            raise ValueError("Report title must be a non-empty string")
        if not isinstance(self.generated_at, datetime):
            raise TypeError("Report timestamp must be a datetime")
        if not isinstance(self.data, Mapping):
            raise TypeError("Report data must be a mapping")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def to_dict(self) -> dict[str, Any]:
        """Return the report as a plain mapping for serialization."""

        return {
            "report_type": self.report_type,
            "title": self.title,
            "generated_at": self.generated_at,
            "data": dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class ClientRiskProfile:
    """Aggregated risk information across a client's sender accounts."""

    client_id: str
    account_numbers: tuple[str, ...]
    total_operations: int
    operations_by_level: Mapping[RiskLevel, int]
    highest_risk_level: RiskLevel
    factor_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_numbers", tuple(self.account_numbers))
        object.__setattr__(
            self, "operations_by_level", MappingProxyType(dict(self.operations_by_level))
        )
        object.__setattr__(self, "factor_counts", MappingProxyType(dict(self.factor_counts)))


@dataclass(frozen=True, slots=True)
class ErrorStatistics:
    """Counts of transaction processing errors."""

    total_errors: int
    errors_by_type: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors_by_type", MappingProxyType(dict(self.errors_by_type)))
