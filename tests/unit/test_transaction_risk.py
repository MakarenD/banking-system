from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from banking_system.accounts import BankAccount, Currency
from banking_system.audit import AuditLevel, AuditLog, RiskAnalyzer, RiskFactor, RiskLevel
from banking_system.reports import AuditReporter
from banking_system.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def make_transaction(
    transaction_id: str,
    sender: BankAccount,
    recipient: BankAccount,
    *,
    amount: int = 100,
) -> Transaction:
    return Transaction(
        TransactionType.INTERNAL_TRANSFER,
        amount,
        Currency.RUB,
        sender,
        recipient,
        transaction_id=transaction_id,
        created_at=NOW,
    )


def test_processor_blocks_high_risk_before_mutation_without_retrying() -> None:
    sender = BankAccount("Alice", balance=200_000, account_id="sender")
    recipient = BankAccount("Bob", balance=500, account_id="recipient")
    audit_log = AuditLog(clock=lambda: NOW)
    processor = TransactionProcessor(
        max_retries=3,
        clock=lambda: NOW,
        audit_log=audit_log,
        risk_analyzer=RiskAnalyzer(large_amount_threshold=100_000),
    )
    transaction = make_transaction("large", sender, recipient, amount=100_000)

    result = processor.process(transaction)

    assert result is transaction
    assert transaction.status is TransactionStatus.FAILED
    assert transaction.attempts == 1
    assert transaction.failure_reason == (
        "Transaction blocked due to high risk: large_amount, new_recipient"
    )
    assert transaction.commission == Decimal("0")
    assert sender.balance == Decimal("200000")
    assert recipient.balance == Decimal("500")
    assert len(processor.errors) == 1
    assert processor.errors[0].error_type == "RiskBlockedError"
    assert [record.level for record in audit_log.records] == [
        AuditLevel.CRITICAL,
        AuditLevel.CRITICAL,
    ]


def test_processor_blocks_night_transfer_to_known_recipient_without_mutation_or_retry() -> None:
    current_time = [NOW]
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", balance=500, account_id="recipient")
    audit_log = AuditLog(clock=lambda: current_time[0])
    analyzer = RiskAnalyzer()
    processor = TransactionProcessor(
        max_retries=3,
        clock=lambda: current_time[0],
        audit_log=audit_log,
        risk_analyzer=analyzer,
    )
    daytime = processor.process(make_transaction("daytime", sender, recipient, amount=10))
    current_time[0] = NOW.replace(hour=2)
    sender_balance = sender.balance
    recipient_balance = recipient.balance

    nighttime = processor.process(make_transaction("nighttime", sender, recipient, amount=10))

    assessment = analyzer.assessments[-1]
    assert daytime.status is TransactionStatus.COMPLETED
    assert assessment.factors == (RiskFactor.NIGHT_OPERATION,)
    assert assessment.level is RiskLevel.MEDIUM
    assert nighttime.status is TransactionStatus.FAILED
    assert nighttime.attempts == 1
    assert nighttime.failure_reason == (
        "Transaction blocked during restricted hours (00:00 to 05:00): night_operation"
    )
    assert nighttime.commission == Decimal("0")
    assert nighttime.received_amount is None
    assert sender.balance == sender_balance
    assert recipient.balance == recipient_balance
    assert len(processor.errors) == 1
    assert processor.errors[0].attempt == 1
    assert processor.errors[0].error_type == "RiskBlockedError"
    assert processor.errors[0].reason == nighttime.failure_reason
    assert [record.event_type for record in audit_log.filter(transaction_id="nighttime")] == [
        "risk_assessment",
        "transaction_error",
    ]


@pytest.mark.parametrize("hour, minute", [(0, 0), (4, 59)])
def test_processor_blocks_restricted_hours_boundaries(hour: int, minute: int) -> None:
    current_time = [NOW]
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer()
    processor = TransactionProcessor(clock=lambda: current_time[0], risk_analyzer=analyzer)
    processor.process(make_transaction("warm-up", sender, recipient, amount=10))
    current_time[0] = NOW.replace(hour=hour, minute=minute)
    balances = (sender.balance, recipient.balance)

    transaction = processor.process(make_transaction("boundary", sender, recipient, amount=10))

    assert transaction.status is TransactionStatus.FAILED
    assert analyzer.assessments[-1].factors == (RiskFactor.NIGHT_OPERATION,)
    assert (sender.balance, recipient.balance) == balances


def test_processor_allows_transfer_at_five_oclock() -> None:
    current_time = [NOW]
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer()
    processor = TransactionProcessor(clock=lambda: current_time[0], risk_analyzer=analyzer)
    processor.process(make_transaction("warm-up", sender, recipient, amount=10))
    current_time[0] = NOW.replace(hour=5, minute=0)

    transaction = processor.process(make_transaction("five-oclock", sender, recipient, amount=10))

    assert transaction.status is TransactionStatus.COMPLETED
    assert analyzer.assessments[-1].factors == ()
    assert sender.balance == Decimal("980")
    assert recipient.balance == Decimal("20")


def test_process_queue_cannot_bypass_restricted_hours() -> None:
    current_time = [NOW]
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer()
    processor = TransactionProcessor(clock=lambda: current_time[0], risk_analyzer=analyzer)
    processor.process(make_transaction("warm-up", sender, recipient, amount=10))
    current_time[0] = NOW.replace(hour=2)
    queue = TransactionQueue(clock=lambda: current_time[0])
    transaction = make_transaction("queued-nighttime", sender, recipient, amount=10)
    queue.add(transaction)
    balances = (sender.balance, recipient.balance)

    processed = processor.process_queue(queue, now=current_time[0])

    assert processed == [transaction]
    assert transaction.status is TransactionStatus.FAILED
    assert transaction.attempts == 1
    assert analyzer.assessments[-1].factors == (RiskFactor.NIGHT_OPERATION,)
    assert (sender.balance, recipient.balance) == balances


def test_processor_audits_allowed_transaction_and_marks_recipient_known() -> None:
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    audit_log = AuditLog(clock=lambda: NOW)
    analyzer = RiskAnalyzer()
    processor = TransactionProcessor(
        clock=lambda: NOW,
        audit_log=audit_log,
        risk_analyzer=analyzer,
    )

    first = processor.process(make_transaction("first", sender, recipient))
    second = processor.process(make_transaction("second", sender, recipient))

    assert first.status is TransactionStatus.COMPLETED
    assert second.status is TransactionStatus.COMPLETED
    assert [assessment.level for assessment in analyzer.assessments] == [
        RiskLevel.MEDIUM,
        RiskLevel.LOW,
    ]
    assert [record.event_type for record in audit_log.records] == [
        "risk_assessment",
        "transaction_completed",
        "risk_assessment",
        "transaction_completed",
    ]


def test_processor_keeps_supporting_sequential_transactions_with_the_same_identifier() -> None:
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    processor = TransactionProcessor(clock=lambda: NOW)

    first = processor.process(make_transaction("duplicate", sender, recipient))
    second = processor.process(make_transaction("duplicate", sender, recipient))

    assert first.status is TransactionStatus.COMPLETED
    assert second.status is TransactionStatus.COMPLETED
    assert sender.balance == Decimal("800")
    assert recipient.balance == Decimal("200")


def test_processor_blocks_operation_that_reaches_frequency_threshold() -> None:
    current_time = [NOW]
    sender = BankAccount("Alice", balance=1_000, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    analyzer = RiskAnalyzer(
        frequent_operations_threshold=3,
        frequency_window=timedelta(minutes=5),
    )
    processor = TransactionProcessor(
        clock=lambda: current_time[0],
        risk_analyzer=analyzer,
    )
    processor.process(make_transaction("first", sender, recipient))
    current_time[0] += timedelta(minutes=1)
    processor.process(make_transaction("second", sender, recipient))
    current_time[0] += timedelta(minutes=1)

    third = processor.process(make_transaction("third", sender, recipient))

    assert third.status is TransactionStatus.FAILED
    assert third.failure_reason == "Transaction blocked due to high risk: frequent_operations"
    assert sender.balance == Decimal("800")
    assert recipient.balance == Decimal("200")


def test_processor_errors_are_available_in_audit_error_report() -> None:
    sender = BankAccount("Alice", balance=10, account_id="sender")
    recipient = BankAccount("Bob", account_id="recipient")
    audit_log = AuditLog(clock=lambda: NOW)
    processor = TransactionProcessor(clock=lambda: NOW, audit_log=audit_log)

    processor.process(make_transaction("failed", sender, recipient, amount=100))

    statistics = AuditReporter(audit_log).error_statistics()
    assert statistics.total_errors == 1
    assert statistics.errors_by_type == {"InsufficientFundsError": 1}
