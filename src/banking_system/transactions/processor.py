"""Transaction processing services."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from banking_system.accounts import (
    AccountClosedError,
    AccountFrozenError,
    AccountStatus,
    Currency,
    InvalidOperationError,
    PremiumAccount,
)
from banking_system.audit import (
    AuditLevel,
    AuditLog,
    RiskAnalyzer,
    RiskAssessment,
    RiskBlockedError,
    RiskFactor,
    RiskLevel,
)

from .enums import TransactionStatus, TransactionType
from .exceptions import ExchangeRateNotFoundError, TransactionStateError
from .models import Amount, Transaction
from .queue import TransactionQueue


@dataclass(frozen=True, slots=True)
class TransactionErrorRecord:
    """A failed transaction processing attempt."""

    transaction_id: str
    attempt: int
    error_type: str
    reason: str
    timestamp: datetime


class TransactionProcessor:
    """Apply commissions, conversion, retries, and error recording."""

    def __init__(
        self,
        *,
        exchange_rates: Mapping[tuple[Currency | str, Currency | str], Amount] | None = None,
        external_fee_rate: Amount = Decimal("0.01"),
        max_retries: int = 0,
        clock: Callable[[], datetime] | None = None,
        audit_log: AuditLog | None = None,
        risk_analyzer: RiskAnalyzer | None = None,
    ) -> None:
        self._exchange_rates = self._validate_exchange_rates(exchange_rates)
        self._external_fee_rate = self._validate_non_negative_decimal(
            external_fee_rate, "External fee rate"
        )
        if isinstance(max_retries, bool) or not isinstance(max_retries, int):
            raise TypeError("Maximum retries must be an integer")
        if max_retries < 0:
            raise ValueError("Maximum retries must not be negative")
        self._max_retries = max_retries
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("Audit log must be an AuditLog instance")
        if risk_analyzer is not None and not isinstance(risk_analyzer, RiskAnalyzer):
            raise TypeError("Risk analyzer must be a RiskAnalyzer instance")
        self._audit_log = audit_log or AuditLog()
        self._risk_analyzer = risk_analyzer or RiskAnalyzer()
        self._errors: list[TransactionErrorRecord] = []

    @property
    def external_fee_rate(self) -> Decimal:
        """Return the fraction charged for external transfers."""

        return self._external_fee_rate

    @property
    def max_retries(self) -> int:
        """Return the number of retries after the first attempt."""

        return self._max_retries

    @property
    def errors(self) -> tuple[TransactionErrorRecord, ...]:
        """Return an immutable snapshot of recorded processing errors."""

        return tuple(self._errors)

    @property
    def audit_log(self) -> AuditLog:
        """Return the audit log used by this processor."""

        return self._audit_log

    @property
    def risk_analyzer(self) -> RiskAnalyzer:
        """Return the risk analyzer used by this processor."""

        return self._risk_analyzer

    def process(self, transaction: Transaction) -> Transaction:
        """Process a pending transaction and return its terminal state."""

        if not isinstance(transaction, Transaction):
            raise TypeError("Processor item must be a Transaction instance")
        if transaction.status is not TransactionStatus.PENDING:
            raise TransactionStateError(
                f"Only pending transactions can be processed, got: {transaction.status.value}"
            )

        assessment_timestamp = self._now()
        assessment = self.risk_analyzer.analyze(transaction, at=assessment_timestamp)
        self._record_assessment(assessment)
        # Restricted hours are a hard business rule, so the night factor blocks
        # independently of the aggregate risk level.
        blocked_for_night = RiskFactor.NIGHT_OPERATION in assessment.factors
        if assessment.level is RiskLevel.HIGH or blocked_for_night:
            transaction._mark_processing(assessment_timestamp)
            factors = ", ".join(factor.value for factor in assessment.factors)
            if blocked_for_night:
                error = RiskBlockedError(
                    "Transaction blocked during restricted hours "
                    f"(00:00 to 05:00): {RiskFactor.NIGHT_OPERATION.value}"
                )
            else:
                error = RiskBlockedError(f"Transaction blocked due to high risk: {factors}")
            error_timestamp = self._now()
            self._record_error(transaction, 1, error, error_timestamp)
            transaction._mark_failed(str(error), error_timestamp)
            return transaction

        for attempt in range(1, self.max_retries + 2):
            timestamp = self._now()
            transaction._mark_processing(timestamp)
            try:
                self._execute(transaction, timestamp)
            except Exception as error:
                error_timestamp = self._now()
                self._record_error(transaction, attempt, error, error_timestamp)
                if attempt > self.max_retries:
                    transaction._mark_failed(str(error), error_timestamp)
                    break
            else:
                transaction._mark_completed(self._now())
                self.risk_analyzer.record_completed(transaction)
                self.audit_log.record(
                    AuditLevel.INFO,
                    "transaction_completed",
                    "Transaction completed",
                    transaction_id=transaction.transaction_id,
                    account_number=transaction.sender.account_number,
                    details={"risk_level": assessment.level.value},
                    timestamp=transaction.processed_at,
                )
                break

        return transaction

    def process_queue(
        self,
        queue: TransactionQueue,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[Transaction]:
        """Process ready queue items and leave delayed items in place."""

        if not isinstance(queue, TransactionQueue):
            raise TypeError("Queue must be a TransactionQueue instance")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("Processing limit must be an integer")
            if limit < 0:
                raise ValueError("Processing limit must not be negative")

        processed: list[Transaction] = []
        while limit is None or len(processed) < limit:
            transaction = queue.get_next(now=now)
            if transaction is None:
                break
            processed.append(self.process(transaction))
        return processed

    def _execute(self, transaction: Transaction, timestamp: datetime) -> None:
        self._ensure_active(transaction.sender, "Sender")
        self._ensure_active(transaction.recipient, "Recipient")
        if transaction.currency is not transaction.sender.currency:
            raise InvalidOperationError("Transaction currency must match sender account currency")

        received_amount = self._convert(
            transaction.amount,
            transaction.currency,
            transaction.recipient.currency,
        )
        external_fee = (
            transaction.amount * self.external_fee_rate
            if transaction.transaction_type is TransactionType.EXTERNAL_TRANSFER
            else Decimal("0")
        )
        account_fee = (
            transaction.sender.fixed_fee
            if isinstance(transaction.sender, PremiumAccount)
            else Decimal("0")
        )
        transaction._set_commission(external_fee + account_fee, timestamp)

        sender_balance = transaction.sender.balance
        recipient_balance = transaction.recipient.balance
        try:
            transaction.sender.withdraw(transaction.amount + external_fee)
            transaction.recipient.deposit(received_amount)
            # The credited amount is stored only after both balance mutations succeed;
            # failed and rolled-back attempts must not look settled to report consumers.
            transaction._set_received_amount(received_amount, timestamp)
        except Exception:
            transaction.sender._restore_balance(sender_balance)
            transaction.recipient._restore_balance(recipient_balance)
            raise

    def _convert(self, amount: Decimal, source: Currency, target: Currency) -> Decimal:
        if source is target:
            return amount
        try:
            rate = self._exchange_rates[(source, target)]
        except KeyError as error:
            raise ExchangeRateNotFoundError(
                f"Exchange rate is not configured: {source.value}/{target.value}"
            ) from error
        return amount * rate

    def _record_error(
        self,
        transaction: Transaction,
        attempt: int,
        error: Exception,
        timestamp: datetime,
    ) -> None:
        self._errors.append(
            TransactionErrorRecord(
                transaction_id=transaction.transaction_id,
                attempt=attempt,
                error_type=type(error).__name__,
                reason=str(error),
                timestamp=timestamp,
            )
        )
        level = AuditLevel.CRITICAL if isinstance(error, RiskBlockedError) else AuditLevel.ERROR
        self.audit_log.record(
            level,
            "transaction_error",
            str(error),
            transaction_id=transaction.transaction_id,
            account_number=transaction.sender.account_number,
            details={
                "attempt": attempt,
                "error_type": type(error).__name__,
            },
            timestamp=timestamp,
        )

    def _record_assessment(self, assessment: RiskAssessment) -> None:
        level_by_risk = {
            RiskLevel.LOW: AuditLevel.INFO,
            RiskLevel.MEDIUM: AuditLevel.WARNING,
            RiskLevel.HIGH: AuditLevel.CRITICAL,
        }
        self.audit_log.record(
            level_by_risk[assessment.level],
            "risk_assessment",
            f"Transaction risk assessed as {assessment.level.value}",
            transaction_id=assessment.transaction_id,
            account_number=assessment.account_number,
            details={
                "recipient_account_number": assessment.recipient_account_number,
                "risk_level": assessment.level.value,
                "risk_score": assessment.score,
                "risk_factors": [factor.value for factor in assessment.factors],
            },
            timestamp=assessment.timestamp,
        )

    def _now(self) -> datetime:
        timestamp = self._clock()
        if not isinstance(timestamp, datetime):
            raise TypeError("Clock must return a datetime")
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    @staticmethod
    def _ensure_active(account: object, role: str) -> None:
        status = getattr(account, "status", None)
        if status is AccountStatus.FROZEN:
            raise AccountFrozenError(f"{role} account is frozen")
        if status is AccountStatus.CLOSED:
            raise AccountClosedError(f"{role} account is closed")

    @classmethod
    def _validate_exchange_rates(
        cls,
        exchange_rates: Mapping[tuple[Currency | str, Currency | str], Amount] | None,
    ) -> dict[tuple[Currency, Currency], Decimal]:
        if exchange_rates is None:
            return {}
        if not isinstance(exchange_rates, Mapping):
            raise TypeError("Exchange rates must be a mapping")

        normalized_rates: dict[tuple[Currency, Currency], Decimal] = {}
        for pair, rate in exchange_rates.items():
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("Exchange rate keys must contain source and target currencies")
            source = cls._validate_currency(pair[0])
            target = cls._validate_currency(pair[1])
            if source is target:
                raise ValueError("Exchange rates between identical currencies are not required")
            normalized_pair = (source, target)
            if normalized_pair in normalized_rates:
                raise ValueError(f"Duplicate exchange rate: {source.value}/{target.value}")
            normalized_rates[normalized_pair] = cls._validate_positive_decimal(
                rate, "Exchange rate"
            )
        return normalized_rates

    @staticmethod
    def _validate_currency(currency: Currency | str) -> Currency:
        if isinstance(currency, Currency):
            return currency
        if isinstance(currency, str):
            try:
                return Currency(currency.strip().upper())
            except ValueError:
                pass
        allowed_currencies = ", ".join(item.value for item in Currency)
        raise ValueError(f"Currency must be one of: {allowed_currencies}")

    @staticmethod
    def _validate_positive_decimal(value: Amount, name: str) -> Decimal:
        normalized_value = TransactionProcessor._validate_decimal(value, name)
        if normalized_value <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return normalized_value

    @staticmethod
    def _validate_non_negative_decimal(value: Amount, name: str) -> Decimal:
        normalized_value = TransactionProcessor._validate_decimal(value, name)
        if normalized_value < 0:
            raise ValueError(f"{name} must not be negative")
        return normalized_value

    @staticmethod
    def _validate_decimal(value: Amount, name: str) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise TypeError(f"{name} must be a number")
        normalized_value = Decimal(str(value))
        if not normalized_value.is_finite():
            raise ValueError(f"{name} must be finite")
        return normalized_value
