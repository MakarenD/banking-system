"""Priority queue for pending transactions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .enums import TransactionStatus
from .exceptions import (
    DuplicateTransactionError,
    TransactionNotFoundError,
    TransactionStateError,
)
from .models import Transaction


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    transaction: Transaction
    priority: int
    available_at: datetime
    sequence: int


class TransactionQueue:
    """Store pending transactions until they are ready for processing."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._entries: dict[str, _QueueEntry] = {}
        self._sequence = 0

    def add(
        self,
        transaction: Transaction,
        *,
        priority: int = 0,
        available_at: datetime | None = None,
    ) -> Transaction:
        """Add a pending transaction and return it."""

        if not isinstance(transaction, Transaction):
            raise TypeError("Queue item must be a Transaction instance")
        if transaction.status is not TransactionStatus.PENDING:
            raise TransactionStateError(
                f"Only pending transactions can be queued, got: {transaction.status.value}"
            )
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("Priority must be an integer")
        if transaction.transaction_id in self._entries:
            raise DuplicateTransactionError(
                f"Transaction is already queued: {transaction.transaction_id}"
            )

        ready_at = self._normalize_timestamp(available_at or self._clock())
        self._entries[transaction.transaction_id] = _QueueEntry(
            transaction=transaction,
            priority=priority,
            available_at=ready_at,
            sequence=self._sequence,
        )
        self._sequence += 1
        return transaction

    def get_next(self, *, now: datetime | None = None) -> Transaction | None:
        """Remove and return the highest-priority transaction that is ready."""

        current_time = self._normalize_timestamp(now or self._clock())
        ready_entries = [
            entry for entry in self._entries.values() if entry.available_at <= current_time
        ]
        if not ready_entries:
            return None

        entry = max(ready_entries, key=lambda item: (item.priority, -item.sequence))
        del self._entries[entry.transaction.transaction_id]
        return entry.transaction

    def cancel(
        self,
        transaction_id: str,
        *,
        reason: str = "Cancelled by request",
    ) -> Transaction:
        """Cancel and remove a pending transaction."""

        if not isinstance(transaction_id, str):
            raise TypeError("Transaction identifier must be a string")
        normalized_transaction_id = transaction_id.strip()
        if not normalized_transaction_id:
            raise ValueError("Transaction identifier must not be empty")
        if not isinstance(reason, str):
            raise TypeError("Cancellation reason must be a string")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Cancellation reason must not be empty")

        try:
            entry = self._entries[normalized_transaction_id]
        except KeyError as error:
            raise TransactionNotFoundError(
                f"Transaction is not queued: {normalized_transaction_id}"
            ) from error

        entry.transaction._mark_cancelled(normalized_reason, self._clock())
        del self._entries[normalized_transaction_id]
        return entry.transaction

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def _normalize_timestamp(timestamp: datetime) -> datetime:
        if not isinstance(timestamp, datetime):
            raise TypeError("Timestamp must be a datetime")
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
