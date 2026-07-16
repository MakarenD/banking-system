import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from banking_system.accounts import BankAccount, Currency
from banking_system.audit import (
    AuditLevel,
    AuditLog,
    RiskAnalyzer,
    RiskFactor,
    RiskLevel,
)
from banking_system.transactions import Transaction, TransactionType

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def make_transaction(
    transaction_id: str,
    sender: BankAccount,
    recipient: BankAccount,
    *,
    amount: int | Decimal = 100,
    created_at: datetime = NOW,
) -> Transaction:
    return Transaction(
        TransactionType.INTERNAL_TRANSFER,
        amount,
        Currency.RUB,
        sender,
        recipient,
        transaction_id=transaction_id,
        created_at=created_at,
    )


def test_audit_log_stores_immutable_records_in_memory_and_jsonl(tmp_path: Path) -> None:
    audit_path = tmp_path / "logs" / "audit.jsonl"
    audit_log = AuditLog(audit_path, clock=lambda: NOW)

    record = audit_log.record(
        " WARNING ",
        " risk_assessment ",
        " Suspicious transfer ",
        transaction_id=" transaction-1 ",
        account_number=" account-1 ",
        details={"amount": Decimal("100.50")},
    )

    assert audit_log.records == (record,)
    assert record.level is AuditLevel.WARNING
    assert record.event_type == "risk_assessment"
    assert record.transaction_id == "transaction-1"
    assert record.account_number == "account-1"
    with pytest.raises(TypeError):
        record.details["amount"] = Decimal("0")  # type: ignore[index]

    stored_record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert stored_record == {
        "timestamp": NOW.isoformat(),
        "level": "warning",
        "event_type": "risk_assessment",
        "message": "Suspicious transfer",
        "transaction_id": "transaction-1",
        "account_number": "account-1",
        "details": {"amount": "100.50"},
    }


def test_audit_log_filters_by_importance_and_domain_fields() -> None:
    audit_log = AuditLog(clock=lambda: NOW)
    first = audit_log.record(
        AuditLevel.INFO,
        "transaction_completed",
        "Completed",
        transaction_id="transaction-1",
        account_number="account-1",
    )
    second = audit_log.record(
        AuditLevel.ERROR,
        "transaction_error",
        "Failed",
        transaction_id="transaction-2",
        account_number="account-1",
    )
    audit_log.record(
        AuditLevel.ERROR,
        "transaction_error",
        "Failed",
        transaction_id="transaction-3",
        account_number="account-2",
    )

    assert audit_log.filter(level="info") == (first,)
    assert audit_log.filter(event_type="transaction_error", account_number="account-1") == (second,)
    assert audit_log.filter(transaction_id="transaction-2") == (second,)


def test_audit_record_deeply_freezes_details_and_rejects_mutable_unsupported_values() -> None:
    audit_log = AuditLog(clock=lambda: NOW)
    source_details = {"factors": ["new_recipient"]}

    record = audit_log.record(
        AuditLevel.INFO, "risk_assessment", "Assessed", details=source_details
    )
    source_details["factors"].append("night_operation")

    assert record.details["factors"] == ("new_recipient",)
    with pytest.raises(TypeError, match="JSON-compatible"):
        audit_log.record(AuditLevel.INFO, "invalid", "Invalid", details={"items": {1, 2}})


@pytest.mark.parametrize(
    "options, error_type",
    [
        ({"large_amount_threshold": 0}, ValueError),
        ({"frequent_operations_threshold": True}, TypeError),
        ({"frequency_window": timedelta(0)}, ValueError),
        ({"night_start_hour": 24}, ValueError),
        ({"night_start_hour": 5, "night_end_hour": 5}, ValueError),
        ({"local_timezone": "UTC"}, TypeError),
    ],
)
def test_risk_analyzer_rejects_invalid_configuration(
    options: dict[str, object], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        RiskAnalyzer(**options)  # type: ignore[arg-type]


def test_new_recipient_is_medium_risk_until_a_transfer_completes() -> None:
    sender = BankAccount("Alice", balance=10_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer()
    first = make_transaction("transaction-1", sender, recipient)

    first_assessment = analyzer.analyze(first, at=NOW)
    analyzer.record_completed(first)
    second_assessment = analyzer.analyze(
        make_transaction("transaction-2", sender, recipient), at=NOW + timedelta(minutes=2)
    )

    assert first_assessment.factors == (RiskFactor.NEW_RECIPIENT,)
    assert first_assessment.level is RiskLevel.MEDIUM
    assert second_assessment.factors == ()
    assert second_assessment.level is RiskLevel.LOW


def test_large_amount_is_high_risk_at_the_inclusive_threshold() -> None:
    sender = BankAccount("Alice", balance=10_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer(large_amount_threshold=1_000)
    warm_up = make_transaction("warm-up", sender, recipient)
    analyzer.analyze(warm_up, at=NOW - timedelta(minutes=2))
    analyzer.record_completed(warm_up)

    assessment = analyzer.analyze(
        make_transaction("large", sender, recipient, amount=1_000), at=NOW
    )

    assert assessment.factors == (RiskFactor.LARGE_AMOUNT,)
    assert assessment.score == 2
    assert assessment.level is RiskLevel.HIGH


def test_frequency_threshold_counts_operations_not_retries() -> None:
    sender = BankAccount("Alice", balance=10_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer(
        frequent_operations_threshold=3,
        frequency_window=timedelta(minutes=5),
    )
    first = make_transaction("transaction-1", sender, recipient)
    analyzer.analyze(first, at=NOW)
    analyzer.record_completed(first)
    analyzer.analyze(
        make_transaction("transaction-2", sender, recipient), at=NOW + timedelta(minutes=1)
    )

    assessment = analyzer.analyze(
        make_transaction("transaction-3", sender, recipient), at=NOW + timedelta(minutes=2)
    )

    assert assessment.factors == (RiskFactor.FREQUENT_OPERATIONS,)
    assert assessment.level is RiskLevel.HIGH


def test_operations_outside_frequency_window_do_not_raise_risk() -> None:
    sender = BankAccount("Alice", balance=10_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer(
        frequent_operations_threshold=2,
        frequency_window=timedelta(minutes=1),
    )
    first = make_transaction("transaction-1", sender, recipient)
    analyzer.analyze(first, at=NOW)
    analyzer.record_completed(first)

    assessment = analyzer.analyze(
        make_transaction("transaction-2", sender, recipient),
        at=NOW + timedelta(minutes=1, seconds=1),
    )

    assert assessment.factors == ()
    assert assessment.level is RiskLevel.LOW


@pytest.mark.parametrize(
    "local_hour, expected",
    [
        (0, True),
        (4, True),
        (5, False),
        (23, False),
    ],
)
def test_night_risk_uses_configured_local_timezone(local_hour: int, expected: bool) -> None:
    moscow_timezone = timezone(timedelta(hours=3))
    local_time = datetime(2026, 7, 16, local_hour, 0, tzinfo=moscow_timezone)
    sender = BankAccount("Alice", balance=10_000, account_id=f"sender-{local_hour}")
    recipient = BankAccount("Bob", account_id=f"recipient-{local_hour}")
    analyzer = RiskAnalyzer(local_timezone=moscow_timezone)
    warm_up = make_transaction(f"warm-up-{local_hour}", sender, recipient)
    analyzer.analyze(warm_up, at=NOW - timedelta(days=1))
    analyzer.record_completed(warm_up)

    assessment = analyzer.analyze(
        make_transaction(f"transaction-{local_hour}", sender, recipient), at=local_time
    )

    assert (RiskFactor.NIGHT_OPERATION in assessment.factors) is expected
    assert assessment.level is (RiskLevel.MEDIUM if expected else RiskLevel.LOW)


def test_new_recipient_at_night_combines_into_high_risk() -> None:
    sender = BankAccount("Alice", balance=10_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer()
    night_time = NOW.replace(hour=2)

    assessment = analyzer.analyze(
        make_transaction("transaction-1", sender, recipient, created_at=night_time),
        at=night_time,
    )

    assert assessment.factors == (
        RiskFactor.NEW_RECIPIENT,
        RiskFactor.NIGHT_OPERATION,
    )
    assert assessment.score == 2
    assert assessment.level is RiskLevel.HIGH
