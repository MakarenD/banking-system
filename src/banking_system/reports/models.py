"""Audit report models."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from banking_system.audit import RiskLevel


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
