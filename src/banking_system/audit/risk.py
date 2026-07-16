"""Transaction risk analysis."""

from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import TYPE_CHECKING

from .enums import RiskFactor, RiskLevel
from .models import RiskAssessment

if TYPE_CHECKING:
    from banking_system.transactions import Transaction

Amount = int | float | Decimal

_FACTOR_WEIGHTS = {
    RiskFactor.LARGE_AMOUNT: 2,
    RiskFactor.FREQUENT_OPERATIONS: 2,
    RiskFactor.NEW_RECIPIENT: 1,
    RiskFactor.NIGHT_OPERATION: 1,
}


class RiskAnalyzer:
    """Detect suspicious transaction patterns and retain assessment history."""

    def __init__(
        self,
        *,
        large_amount_threshold: Amount = 100_000,
        frequent_operations_threshold: int = 11,
        frequency_window: timedelta = timedelta(minutes=1),
        night_start_hour: int = 0,
        night_end_hour: int = 5,
        local_timezone: tzinfo = timezone.utc,
    ) -> None:
        self._large_amount_threshold = self._validate_positive_decimal(
            large_amount_threshold, "Large amount threshold"
        )
        self._frequent_operations_threshold = self._validate_positive_integer(
            frequent_operations_threshold, "Frequent operations threshold"
        )
        if not isinstance(frequency_window, timedelta):
            raise TypeError("Frequency window must be a timedelta")
        if frequency_window <= timedelta(0):
            raise ValueError("Frequency window must be greater than zero")
        self._frequency_window = frequency_window
        self._night_start_hour = self._validate_hour(night_start_hour, "Night start hour")
        self._night_end_hour = self._validate_hour(night_end_hour, "Night end hour")
        if self._night_start_hour == self._night_end_hour:
            raise ValueError("Night start and end hours must be different")
        if not isinstance(local_timezone, tzinfo):
            raise TypeError("Local timezone must implement tzinfo")
        self._local_timezone = local_timezone
        self._assessments: list[RiskAssessment] = []
        self._known_recipients: dict[str, set[str]] = {}

    @property
    def assessments(self) -> tuple[RiskAssessment, ...]:
        """Return an immutable snapshot of completed assessments."""

        return tuple(self._assessments)

    @property
    def large_amount_threshold(self) -> Decimal:
        """Return the inclusive threshold for a large operation."""

        return self._large_amount_threshold

    def analyze(self, transaction: "Transaction", *, at: datetime | None = None) -> RiskAssessment:
        """Analyze and remember one transaction attempt."""

        from banking_system.transactions import Transaction

        if not isinstance(transaction, Transaction):
            raise TypeError("Risk analyzer item must be a Transaction instance")
        timestamp = self._normalize_timestamp(at or transaction.created_at)
        account_number = transaction.sender.account_number
        recipient_account_number = transaction.recipient.account_number
        factors: list[RiskFactor] = []

        if transaction.amount >= self.large_amount_threshold:
            factors.append(RiskFactor.LARGE_AMOUNT)
        if self._is_frequent(account_number, timestamp):
            factors.append(RiskFactor.FREQUENT_OPERATIONS)
        if recipient_account_number not in self._known_recipients.get(account_number, set()):
            factors.append(RiskFactor.NEW_RECIPIENT)
        if self._is_night(timestamp):
            factors.append(RiskFactor.NIGHT_OPERATION)

        score = sum(_FACTOR_WEIGHTS[factor] for factor in factors)
        if score >= 2:
            level = RiskLevel.HIGH
        elif score:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        assessment = RiskAssessment(
            transaction_id=transaction.transaction_id,
            account_number=account_number,
            recipient_account_number=recipient_account_number,
            timestamp=timestamp,
            level=level,
            factors=tuple(factors),
            score=score,
        )
        self._assessments.append(assessment)
        return assessment

    def record_completed(self, transaction: "Transaction") -> None:
        """Remember a recipient after a transfer completes successfully."""

        from banking_system.transactions import Transaction

        if not isinstance(transaction, Transaction):
            raise TypeError("Completed risk item must be a Transaction instance")
        self._known_recipients.setdefault(transaction.sender.account_number, set()).add(
            transaction.recipient.account_number
        )

    def _is_frequent(self, account_number: str, timestamp: datetime) -> bool:
        window_start = timestamp - self._frequency_window
        previous_operations = sum(
            assessment.account_number == account_number
            and window_start <= assessment.timestamp <= timestamp
            for assessment in self._assessments
        )
        return previous_operations + 1 >= self._frequent_operations_threshold

    def _is_night(self, timestamp: datetime) -> bool:
        local_hour = timestamp.astimezone(self._local_timezone).hour
        if self._night_start_hour < self._night_end_hour:
            return self._night_start_hour <= local_hour < self._night_end_hour
        return local_hour >= self._night_start_hour or local_hour < self._night_end_hour

    @staticmethod
    def _validate_positive_decimal(value: Amount, name: str) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise TypeError(f"{name} must be a number")
        normalized_value = Decimal(str(value))
        if not normalized_value.is_finite():
            raise ValueError(f"{name} must be finite")
        if normalized_value <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return normalized_value

    @staticmethod
    def _validate_positive_integer(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return value

    @staticmethod
    def _validate_hour(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 23:
            raise ValueError(f"{name} must be between 0 and 23")
        return value

    @staticmethod
    def _normalize_timestamp(timestamp: datetime) -> datetime:
        if not isinstance(timestamp, datetime):
            raise TypeError("Risk timestamp must be a datetime")
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
