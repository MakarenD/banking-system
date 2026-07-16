"""Reports derived from audit records."""

from collections import Counter

from banking_system.audit import AuditLog, AuditRecord, RiskLevel
from banking_system.clients import Client

from .models import ClientRiskProfile, ErrorStatistics

_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}


class AuditReporter:
    """Build suspicious-operation, client-risk, and error reports."""

    def __init__(self, audit_log: AuditLog) -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("Audit reporter requires an AuditLog instance")
        self._audit_log = audit_log

    def suspicious_operations(self) -> tuple[AuditRecord, ...]:
        """Return medium- and high-risk transaction assessments."""

        return tuple(
            record
            for record in self._audit_log.filter(event_type="risk_assessment")
            if self._risk_level(record) in {RiskLevel.MEDIUM, RiskLevel.HIGH}
        )

    def client_risk_profile(self, client: Client) -> ClientRiskProfile:
        """Aggregate transaction risk across a client's sender accounts."""

        if not isinstance(client, Client):
            raise TypeError("Client risk profile requires a Client instance")
        account_numbers = tuple(client.account_numbers)
        records = tuple(
            record
            for record in self._audit_log.filter(event_type="risk_assessment")
            if record.account_number in account_numbers
        )
        level_counts = Counter(self._risk_level(record) for record in records)
        factor_counts = Counter(
            factor for record in records for factor in record.details.get("risk_factors", [])
        )
        highest_risk_level = max(
            level_counts,
            key=lambda level: _RISK_ORDER[level],
            default=RiskLevel.LOW,
        )
        return ClientRiskProfile(
            client_id=client.client_id,
            account_numbers=account_numbers,
            total_operations=len(records),
            operations_by_level={level: level_counts[level] for level in RiskLevel},
            highest_risk_level=highest_risk_level,
            factor_counts=dict(factor_counts),
        )

    def error_statistics(self) -> ErrorStatistics:
        """Count transaction errors by exception type."""

        records = self._audit_log.filter(event_type="transaction_error")
        error_counts = Counter(str(record.details["error_type"]) for record in records)
        return ErrorStatistics(total_errors=len(records), errors_by_type=dict(error_counts))

    @staticmethod
    def _risk_level(record: AuditRecord) -> RiskLevel:
        return RiskLevel(str(record.details["risk_level"]))
