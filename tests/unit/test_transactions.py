from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from banking_system.accounts import (
    AccountStatus,
    BankAccount,
    Currency,
    InvalidOperationError,
    PremiumAccount,
)
from banking_system.transactions import (
    DuplicateTransactionError,
    Transaction,
    TransactionNotFoundError,
    TransactionProcessor,
    TransactionQueue,
    TransactionStateError,
    TransactionStatus,
    TransactionType,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_transaction(
    *,
    transaction_id: str = "transaction-1",
    transaction_type: TransactionType | str = TransactionType.INTERNAL_TRANSFER,
    amount: object = 100,
    currency: Currency | str = Currency.RUB,
    sender: BankAccount | None = None,
    recipient: BankAccount | None = None,
) -> Transaction:
    return Transaction(
        transaction_type,
        amount,  # type: ignore[arg-type]
        currency,
        sender or BankAccount("Alice", balance=1_000, currency=currency),
        recipient or BankAccount("Bob", currency=currency),
        transaction_id=transaction_id,
        created_at=NOW,
    )


class FlakyBankAccount(BankAccount):
    def __init__(self, *args: object, failures: int, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.failures = failures

    def withdraw(self, amount: object) -> Decimal:
        if self.failures:
            self.failures -= 1
            raise InvalidOperationError("Temporary withdrawal failure")
        return super().withdraw(amount)  # type: ignore[arg-type]


class FailingRecipientAccount(BankAccount):
    def deposit(self, amount: object) -> Decimal:
        super().deposit(amount)  # type: ignore[arg-type]
        raise InvalidOperationError("Recipient deposit failure")


def test_transaction_normalizes_public_state_and_starts_pending() -> None:
    sender = BankAccount("Alice", balance=1_000, currency=Currency.USD)
    recipient = BankAccount("Bob", currency=Currency.USD)

    transaction = Transaction(
        " INTERNAL_TRANSFER ",
        100.25,
        " usd ",
        sender,
        recipient,
        transaction_id=" transaction-1 ",
        created_at=NOW.replace(tzinfo=None),
    )

    assert transaction.transaction_id == "transaction-1"
    assert transaction.transaction_type is TransactionType.INTERNAL_TRANSFER
    assert transaction.amount == Decimal("100.25")
    assert transaction.currency is Currency.USD
    assert transaction.sender is sender
    assert transaction.recipient is recipient
    assert transaction.commission == Decimal("0")
    assert transaction.status is TransactionStatus.PENDING
    assert transaction.failure_reason is None
    assert transaction.attempts == 0
    assert transaction.timestamps == {
        "created_at": NOW,
        "updated_at": NOW,
        "processed_at": None,
    }


@pytest.mark.parametrize("amount", [0, -1, True, "100", float("nan"), float("inf")])
def test_transaction_rejects_invalid_amount(amount: object) -> None:
    with pytest.raises(InvalidOperationError):
        make_transaction(amount=amount)


def test_transaction_requires_distinct_bank_accounts() -> None:
    account = BankAccount("Alice", balance=1_000)

    with pytest.raises(ValueError, match="different accounts"):
        make_transaction(sender=account, recipient=account)

    with pytest.raises(TypeError, match="BankAccount instances"):
        Transaction(
            TransactionType.INTERNAL_TRANSFER,
            100,
            Currency.RUB,
            account,
            "Bob",  # type: ignore[arg-type]
        )


def test_transaction_public_state_is_read_only() -> None:
    transaction = make_transaction()

    with pytest.raises(AttributeError):
        transaction.status = TransactionStatus.COMPLETED  # type: ignore[misc]
    with pytest.raises(TypeError):
        transaction.timestamps["processed_at"] = NOW  # type: ignore[index]


def test_queue_prioritizes_ready_transactions_and_preserves_fifo_ties() -> None:
    queue = TransactionQueue(clock=lambda: NOW)
    low = make_transaction(transaction_id="low")
    first_high = make_transaction(transaction_id="first-high")
    second_high = make_transaction(transaction_id="second-high")

    queue.add(low, priority=1)
    queue.add(first_high, priority=10)
    queue.add(second_high, priority=10)

    assert queue.get_next() is first_high
    assert queue.get_next() is second_high
    assert queue.get_next() is low
    assert queue.get_next() is None


def test_queue_keeps_delayed_transactions_until_available() -> None:
    queue = TransactionQueue(clock=lambda: NOW)
    delayed = make_transaction()
    available_at = NOW + timedelta(hours=1)
    queue.add(delayed, available_at=available_at)

    assert queue.get_next(now=available_at - timedelta(seconds=1)) is None
    assert len(queue) == 1
    assert queue.get_next(now=available_at) is delayed
    assert len(queue) == 0


def test_queue_cancels_transaction_and_rejects_duplicate_or_missing_entries() -> None:
    queue = TransactionQueue(clock=lambda: NOW)
    transaction = make_transaction()
    queue.add(transaction)

    with pytest.raises(DuplicateTransactionError):
        queue.add(transaction)

    cancelled = queue.cancel(transaction.transaction_id, reason="Customer request")

    assert cancelled is transaction
    assert transaction.status is TransactionStatus.CANCELLED
    assert transaction.failure_reason == "Customer request"
    assert transaction.processed_at == NOW
    assert queue.get_next() is None
    with pytest.raises(TransactionNotFoundError):
        queue.cancel(transaction.transaction_id)
    with pytest.raises(TransactionStateError):
        TransactionProcessor().process(transaction)


def test_processor_completes_internal_transfer_without_external_fee() -> None:
    sender = BankAccount("Alice", balance=1_000)
    recipient = BankAccount("Bob", balance=100)
    transaction = make_transaction(sender=sender, recipient=recipient, amount=200)

    result = TransactionProcessor(clock=lambda: NOW).process(transaction)

    assert result is transaction
    assert transaction.status is TransactionStatus.COMPLETED
    assert transaction.commission == Decimal("0")
    assert transaction.attempts == 1
    assert transaction.failure_reason is None
    assert transaction.processed_at == NOW
    assert sender.balance == Decimal("800")
    assert recipient.balance == Decimal("300")


def test_processor_charges_configured_external_transfer_fee() -> None:
    sender = BankAccount("Alice", balance=1_000)
    recipient = BankAccount("Bob")
    transaction = make_transaction(
        transaction_type=TransactionType.EXTERNAL_TRANSFER,
        sender=sender,
        recipient=recipient,
        amount=100,
    )
    processor = TransactionProcessor(external_fee_rate=Decimal("0.025"), clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.COMPLETED
    assert transaction.commission == Decimal("2.500")
    assert sender.balance == Decimal("897.500")
    assert recipient.balance == Decimal("100")


def test_processor_converts_amount_for_recipient_currency() -> None:
    sender = BankAccount("Alice", balance=1_000, currency=Currency.USD)
    recipient = BankAccount("Bob", currency=Currency.RUB)
    transaction = make_transaction(
        sender=sender,
        recipient=recipient,
        amount=100,
        currency=Currency.USD,
    )
    processor = TransactionProcessor(
        exchange_rates={(Currency.USD, Currency.RUB): Decimal("90.5")},
        clock=lambda: NOW,
    )

    processor.process(transaction)

    assert transaction.status is TransactionStatus.COMPLETED
    assert sender.balance == Decimal("900")
    assert recipient.balance == Decimal("9050.0")


def test_processor_fails_without_exchange_rate_and_preserves_balances() -> None:
    sender = BankAccount("Alice", balance=1_000, currency=Currency.USD)
    recipient = BankAccount("Bob", balance=500, currency=Currency.EUR)
    transaction = make_transaction(
        sender=sender,
        recipient=recipient,
        amount=100,
        currency=Currency.USD,
    )
    processor = TransactionProcessor(clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.failure_reason == "Exchange rate is not configured: USD/EUR"
    assert sender.balance == Decimal("1000")
    assert recipient.balance == Decimal("500")
    assert processor.errors[0].error_type == "ExchangeRateNotFoundError"


def test_standard_account_cannot_cover_transfer_and_fee_with_negative_balance() -> None:
    sender = BankAccount("Alice", balance=100)
    recipient = BankAccount("Bob")
    transaction = make_transaction(
        transaction_type=TransactionType.EXTERNAL_TRANSFER,
        sender=sender,
        recipient=recipient,
        amount=100,
    )
    processor = TransactionProcessor(external_fee_rate=Decimal("0.01"), clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.failure_reason == "Insufficient funds"
    assert transaction.commission == Decimal("1.00")
    assert sender.balance == Decimal("100")
    assert recipient.balance == Decimal("0")


def test_premium_account_can_use_overdraft_and_records_account_fee() -> None:
    sender = PremiumAccount(
        "Alice",
        balance=50,
        withdrawal_limit=200,
        overdraft_limit=60,
        fixed_fee=10,
    )
    recipient = BankAccount("Bob")
    transaction = make_transaction(sender=sender, recipient=recipient, amount=100)

    TransactionProcessor(clock=lambda: NOW).process(transaction)

    assert transaction.status is TransactionStatus.COMPLETED
    assert transaction.commission == Decimal("10")
    assert sender.balance == Decimal("-60")
    assert recipient.balance == Decimal("100")


@pytest.mark.parametrize("inactive_role", ["sender", "recipient"])
@pytest.mark.parametrize(
    "inactive_status, status_name",
    [
        (AccountStatus.FROZEN, "frozen"),
        (AccountStatus.CLOSED, "closed"),
    ],
)
def test_inactive_account_rejects_transfer_without_mutation(
    inactive_role: str,
    inactive_status: AccountStatus,
    status_name: str,
) -> None:
    sender_status = inactive_status if inactive_role == "sender" else AccountStatus.ACTIVE
    recipient_status = inactive_status if inactive_role == "recipient" else AccountStatus.ACTIVE
    sender = BankAccount("Alice", balance=1_000, status=sender_status)
    recipient = BankAccount("Bob", balance=100, status=recipient_status)
    transaction = make_transaction(sender=sender, recipient=recipient)
    processor = TransactionProcessor(clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.failure_reason == f"{inactive_role.title()} account is {status_name}"
    assert sender.balance == Decimal("1000")
    assert recipient.balance == Decimal("100")


def test_processor_rejects_transaction_currency_different_from_sender() -> None:
    sender = BankAccount("Alice", balance=1_000, currency=Currency.USD)
    recipient = BankAccount("Bob", currency=Currency.EUR)
    transaction = make_transaction(
        sender=sender,
        recipient=recipient,
        amount=100,
        currency=Currency.EUR,
    )
    processor = TransactionProcessor(
        exchange_rates={(Currency.EUR, Currency.USD): Decimal("1.1")},
        clock=lambda: NOW,
    )

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.failure_reason == "Transaction currency must match sender account currency"
    assert sender.balance == Decimal("1000")
    assert recipient.balance == Decimal("0")


def test_processor_retries_transient_error_and_keeps_error_history() -> None:
    sender = FlakyBankAccount("Alice", balance=1_000, failures=1)
    recipient = BankAccount("Bob")
    transaction = make_transaction(sender=sender, recipient=recipient)
    processor = TransactionProcessor(max_retries=2, clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.COMPLETED
    assert transaction.attempts == 2
    assert transaction.failure_reason is None
    assert sender.balance == Decimal("900")
    assert recipient.balance == Decimal("100")
    assert len(processor.errors) == 1
    assert processor.errors[0].attempt == 1
    assert processor.errors[0].reason == "Temporary withdrawal failure"


def test_processor_marks_transaction_failed_after_retry_limit() -> None:
    sender = FlakyBankAccount("Alice", balance=1_000, failures=10)
    recipient = BankAccount("Bob")
    transaction = make_transaction(sender=sender, recipient=recipient)
    processor = TransactionProcessor(max_retries=2, clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.attempts == 3
    assert transaction.failure_reason == "Temporary withdrawal failure"
    assert [error.attempt for error in processor.errors] == [1, 2, 3]
    assert sender.balance == Decimal("1000")
    assert recipient.balance == Decimal("0")


def test_processor_rolls_back_both_balances_when_recipient_fails_after_deposit() -> None:
    sender = BankAccount("Alice", balance=1_000)
    recipient = FailingRecipientAccount("Bob", balance=50)
    transaction = make_transaction(sender=sender, recipient=recipient)
    processor = TransactionProcessor(max_retries=1, clock=lambda: NOW)

    processor.process(transaction)

    assert transaction.status is TransactionStatus.FAILED
    assert transaction.attempts == 2
    assert transaction.failure_reason == "Recipient deposit failure"
    assert sender.balance == Decimal("1000")
    assert recipient.balance == Decimal("50")
    assert len(processor.errors) == 2


def test_queue_processes_ten_transactions() -> None:
    sender = BankAccount("Alice", balance=1_000)
    recipient = BankAccount("Bob")
    queue = TransactionQueue(clock=lambda: NOW)
    transactions = [
        make_transaction(
            transaction_id=f"transaction-{index}",
            sender=sender,
            recipient=recipient,
            amount=10,
        )
        for index in range(10)
    ]
    for index, transaction in enumerate(transactions):
        queue.add(transaction, priority=index % 3)

    processed = TransactionProcessor(clock=lambda: NOW).process_queue(queue, now=NOW)

    assert len(processed) == 10
    assert all(transaction.status is TransactionStatus.COMPLETED for transaction in processed)
    assert sender.balance == Decimal("900")
    assert recipient.balance == Decimal("100")
    assert len(queue) == 0


@pytest.mark.parametrize(
    "options, error_type",
    [
        ({"external_fee_rate": -0.01}, ValueError),
        ({"external_fee_rate": float("nan")}, ValueError),
        ({"max_retries": -1}, ValueError),
        ({"max_retries": True}, TypeError),
        ({"exchange_rates": {("USD", "EUR"): 0}}, ValueError),
    ],
)
def test_processor_rejects_invalid_configuration(
    options: dict[str, object], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        TransactionProcessor(**options)  # type: ignore[arg-type]
