"""Transaction domain models."""

from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from banking_system.accounts import BankAccount, Currency, InvalidOperationError

from .enums import TransactionStatus, TransactionType
from .exceptions import TransactionStateError

Amount = int | float | Decimal


class Transaction:
    """A transfer between two bank accounts."""

    def __init__(
        self,
        transaction_type: TransactionType | str,
        amount: Amount,
        currency: Currency | str,
        sender: BankAccount,
        recipient: BankAccount,
        *,
        transaction_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._transaction_id = self._validate_transaction_id(transaction_id)
        self._transaction_type = self._validate_transaction_type(transaction_type)
        self._amount = self._validate_amount(amount)
        self._currency = self._validate_currency(currency)
        self._sender, self._recipient = self._validate_accounts(sender, recipient)
        self._commission = Decimal("0")
        self._status = TransactionStatus.PENDING
        self._failure_reason: str | None = None
        self._attempts = 0
        self._created_at = self._normalize_timestamp(created_at or datetime.now(timezone.utc))
        self._updated_at = self._created_at
        self._processed_at: datetime | None = None

    @property
    def transaction_id(self) -> str:
        """Return the transaction identifier."""

        return self._transaction_id

    @property
    def transaction_type(self) -> TransactionType:
        """Return the transfer type."""

        return self._transaction_type

    @property
    def amount(self) -> Decimal:
        """Return the amount sent before commission."""

        return self._amount

    @property
    def currency(self) -> Currency:
        """Return the transaction currency."""

        return self._currency

    @property
    def commission(self) -> Decimal:
        """Return the total commission charged to the sender."""

        return self._commission

    @property
    def sender(self) -> BankAccount:
        """Return the source account."""

        return self._sender

    @property
    def recipient(self) -> BankAccount:
        """Return the destination account."""

        return self._recipient

    @property
    def status(self) -> TransactionStatus:
        """Return the current lifecycle state."""

        return self._status

    @property
    def failure_reason(self) -> str | None:
        """Return the final processing or cancellation reason."""

        return self._failure_reason

    @property
    def attempts(self) -> int:
        """Return the number of processing attempts."""

        return self._attempts

    @property
    def created_at(self) -> datetime:
        """Return when the transaction was created."""

        return self._created_at

    @property
    def updated_at(self) -> datetime:
        """Return when the transaction state last changed."""

        return self._updated_at

    @property
    def processed_at(self) -> datetime | None:
        """Return when the transaction reached a terminal state."""

        return self._processed_at

    @property
    def timestamps(self) -> MappingProxyType[str, datetime | None]:
        """Return an immutable view of transaction timestamps."""

        return MappingProxyType(
            {
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "processed_at": self.processed_at,
            }
        )

    def get_transaction_info(self) -> dict[str, Any]:
        """Return the public transaction state."""

        return {
            "transaction_id": self.transaction_id,
            "transaction_type": self.transaction_type.value,
            "amount": self.amount,
            "currency": self.currency.value,
            "commission": self.commission,
            "sender_account": self.sender.account_number,
            "recipient_account": self.recipient.account_number,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
            "attempts": self.attempts,
            **self.timestamps,
        }

    def _mark_processing(self, timestamp: datetime) -> None:
        if self.status not in {TransactionStatus.PENDING, TransactionStatus.PROCESSING}:
            raise TransactionStateError(
                f"Transaction cannot be processed from status: {self.status.value}"
            )

        self._status = TransactionStatus.PROCESSING
        self._failure_reason = None
        self._attempts += 1
        self._updated_at = self._normalize_timestamp(timestamp)

    def _set_commission(self, commission: Decimal, timestamp: datetime) -> None:
        self._commission = commission
        self._updated_at = self._normalize_timestamp(timestamp)

    def _mark_completed(self, timestamp: datetime) -> None:
        normalized_timestamp = self._normalize_timestamp(timestamp)
        self._status = TransactionStatus.COMPLETED
        self._failure_reason = None
        self._updated_at = normalized_timestamp
        self._processed_at = normalized_timestamp

    def _mark_failed(self, reason: str, timestamp: datetime) -> None:
        normalized_timestamp = self._normalize_timestamp(timestamp)
        self._status = TransactionStatus.FAILED
        self._failure_reason = reason
        self._updated_at = normalized_timestamp
        self._processed_at = normalized_timestamp

    def _mark_cancelled(self, reason: str, timestamp: datetime) -> None:
        if self.status is not TransactionStatus.PENDING:
            raise TransactionStateError(
                f"Transaction cannot be cancelled from status: {self.status.value}"
            )

        normalized_timestamp = self._normalize_timestamp(timestamp)
        self._status = TransactionStatus.CANCELLED
        self._failure_reason = reason
        self._updated_at = normalized_timestamp
        self._processed_at = normalized_timestamp

    @staticmethod
    def _validate_transaction_id(transaction_id: str | None) -> str:
        if transaction_id is None:
            return uuid4().hex[:8]
        if not isinstance(transaction_id, str):
            raise TypeError("Transaction identifier must be a string")

        normalized_transaction_id = transaction_id.strip()
        if not normalized_transaction_id:
            raise ValueError("Transaction identifier must not be empty")
        return normalized_transaction_id

    @staticmethod
    def _validate_transaction_type(
        transaction_type: TransactionType | str,
    ) -> TransactionType:
        if isinstance(transaction_type, TransactionType):
            return transaction_type
        if isinstance(transaction_type, str):
            try:
                return TransactionType(transaction_type.strip().lower())
            except ValueError:
                pass

        allowed_types = ", ".join(item.value for item in TransactionType)
        raise ValueError(f"Transaction type must be one of: {allowed_types}")

    @staticmethod
    def _validate_amount(amount: Amount) -> Decimal:
        if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
            raise InvalidOperationError("Transaction amount must be a number")

        normalized_amount = Decimal(str(amount))
        if not normalized_amount.is_finite():
            raise InvalidOperationError("Transaction amount must be finite")
        if normalized_amount <= 0:
            raise InvalidOperationError("Transaction amount must be greater than zero")
        return normalized_amount

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
    def _validate_accounts(
        sender: BankAccount, recipient: BankAccount
    ) -> tuple[BankAccount, BankAccount]:
        if not isinstance(sender, BankAccount) or not isinstance(recipient, BankAccount):
            raise TypeError("Sender and recipient must be BankAccount instances")
        if sender is recipient:
            raise ValueError("Sender and recipient must be different accounts")
        return sender, recipient

    @staticmethod
    def _normalize_timestamp(timestamp: datetime) -> datetime:
        if not isinstance(timestamp, datetime):
            raise TypeError("Timestamp must be a datetime")
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
