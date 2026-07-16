from datetime import datetime, timezone

from banking_system.audit import AuditLevel, AuditLog, RiskFactor, RiskLevel
from banking_system.bank import Bank
from banking_system.clients import Client
from banking_system.reports import AuditReporter

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def make_client_with_accounts(*account_numbers: str) -> Client:
    bank = Bank(clock=lambda: NOW)
    client = bank.add_client(
        Client(
            "Alice Smith",
            30,
            {"email": "alice@example.com"},
            "correct-password",
            client_id="client-1",
        )
    )
    for account_number in account_numbers:
        bank.open_account(client.client_id, account_id=account_number)
    return client


def record_assessment(
    audit_log: AuditLog,
    transaction_id: str,
    account_number: str,
    level: RiskLevel,
    *factors: RiskFactor,
) -> None:
    audit_levels = {
        RiskLevel.LOW: AuditLevel.INFO,
        RiskLevel.MEDIUM: AuditLevel.WARNING,
        RiskLevel.HIGH: AuditLevel.CRITICAL,
    }
    audit_log.record(
        audit_levels[level],
        "risk_assessment",
        "Risk assessed",
        transaction_id=transaction_id,
        account_number=account_number,
        details={
            "risk_level": level.value,
            "risk_factors": [factor.value for factor in factors],
        },
        timestamp=NOW,
    )


def test_suspicious_operations_report_excludes_low_risk_transactions() -> None:
    audit_log = AuditLog()
    record_assessment(audit_log, "low", "account-1", RiskLevel.LOW)
    record_assessment(
        audit_log,
        "medium",
        "account-1",
        RiskLevel.MEDIUM,
        RiskFactor.NEW_RECIPIENT,
    )
    record_assessment(
        audit_log,
        "high",
        "account-2",
        RiskLevel.HIGH,
        RiskFactor.LARGE_AMOUNT,
    )

    report = AuditReporter(audit_log).suspicious_operations()

    assert [record.transaction_id for record in report] == ["medium", "high"]


def test_client_risk_profile_aggregates_levels_and_factors_across_sender_accounts() -> None:
    audit_log = AuditLog()
    record_assessment(audit_log, "low", "account-1", RiskLevel.LOW)
    record_assessment(
        audit_log,
        "medium",
        "account-1",
        RiskLevel.MEDIUM,
        RiskFactor.NEW_RECIPIENT,
    )
    record_assessment(
        audit_log,
        "high",
        "account-1",
        RiskLevel.HIGH,
        RiskFactor.NEW_RECIPIENT,
        RiskFactor.NIGHT_OPERATION,
    )
    record_assessment(audit_log, "second-account", "account-3", RiskLevel.LOW)
    record_assessment(audit_log, "other", "account-2", RiskLevel.HIGH)
    client = make_client_with_accounts("account-1", "account-3")

    profile = AuditReporter(audit_log).client_risk_profile(client)

    assert profile.client_id == "client-1"
    assert profile.account_numbers == ("account-1", "account-3")
    assert profile.total_operations == 4
    assert profile.operations_by_level == {
        RiskLevel.LOW: 2,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 1,
    }
    assert profile.highest_risk_level is RiskLevel.HIGH
    assert profile.factor_counts == {
        RiskFactor.NEW_RECIPIENT.value: 2,
        RiskFactor.NIGHT_OPERATION.value: 1,
    }


def test_client_risk_profile_is_empty_for_unknown_account() -> None:
    client = make_client_with_accounts()

    profile = AuditReporter(AuditLog()).client_risk_profile(client)

    assert profile.client_id == "client-1"
    assert profile.account_numbers == ()
    assert profile.total_operations == 0
    assert profile.highest_risk_level is RiskLevel.LOW
    assert all(count == 0 for count in profile.operations_by_level.values())
    assert profile.factor_counts == {}


def test_error_statistics_counts_every_processing_error_by_type() -> None:
    audit_log = AuditLog()
    for error_type in ["InvalidOperationError", "InvalidOperationError", "RiskBlockedError"]:
        audit_log.record(
            AuditLevel.ERROR,
            "transaction_error",
            "Transaction failed",
            details={"error_type": error_type},
            timestamp=NOW,
        )

    statistics = AuditReporter(audit_log).error_statistics()

    assert statistics.total_errors == 3
    assert statistics.errors_by_type == {
        "InvalidOperationError": 2,
        "RiskBlockedError": 1,
    }
