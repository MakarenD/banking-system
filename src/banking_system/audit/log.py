"""In-memory and JSON Lines audit storage."""

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .enums import AuditLevel
from .models import AuditRecord


class AuditLog:
    """Store audit records in memory and optionally append them to a file."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if file_path is not None and not isinstance(file_path, (str, Path)):
            raise TypeError("Audit file path must be a string or Path")

        self._file_path = Path(file_path) if file_path is not None else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._records: list[AuditRecord] = []

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        """Return an immutable snapshot of all in-memory records."""

        return tuple(self._records)

    @property
    def file_path(self) -> Path | None:
        """Return the configured JSON Lines file path."""

        return self._file_path

    def record(
        self,
        level: AuditLevel | str,
        event_type: str,
        message: str,
        *,
        transaction_id: str | None = None,
        account_number: str | None = None,
        details: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> AuditRecord:
        """Create, store, and return an audit record."""

        record = AuditRecord(
            timestamp=self._normalize_timestamp(timestamp or self._clock()),
            level=self._validate_level(level),
            event_type=self._validate_text(event_type, "Event type"),
            message=self._validate_text(message, "Message"),
            transaction_id=self._validate_optional_text(transaction_id, "Transaction identifier"),
            account_number=self._validate_optional_text(account_number, "Account number"),
            details=self._validate_details(details),
        )
        self._records.append(record)
        if self.file_path is not None:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def filter(
        self,
        *,
        level: AuditLevel | str | None = None,
        event_type: str | None = None,
        transaction_id: str | None = None,
        account_number: str | None = None,
    ) -> tuple[AuditRecord, ...]:
        """Return records that match every supplied field."""

        normalized_level = self._validate_level(level) if level is not None else None
        normalized_event_type = (
            self._validate_text(event_type, "Event type") if event_type is not None else None
        )
        normalized_transaction_id = self._validate_optional_text(
            transaction_id, "Transaction identifier"
        )
        normalized_account_number = self._validate_optional_text(account_number, "Account number")

        return tuple(
            record
            for record in self._records
            if (normalized_level is None or record.level is normalized_level)
            and (normalized_event_type is None or record.event_type == normalized_event_type)
            and (
                normalized_transaction_id is None
                or record.transaction_id == normalized_transaction_id
            )
            and (
                normalized_account_number is None
                or record.account_number == normalized_account_number
            )
        )

    @staticmethod
    def _validate_level(level: AuditLevel | str) -> AuditLevel:
        if isinstance(level, AuditLevel):
            return level
        if isinstance(level, str):
            try:
                return AuditLevel(level.strip().lower())
            except ValueError:
                pass
        allowed_levels = ", ".join(item.value for item in AuditLevel)
        raise ValueError(f"Audit level must be one of: {allowed_levels}")

    @staticmethod
    def _validate_text(value: str, name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{name} must not be empty")
        return normalized_value

    @classmethod
    def _validate_optional_text(cls, value: str | None, name: str) -> str | None:
        if value is None:
            return None
        return cls._validate_text(value, name)

    @staticmethod
    def _validate_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
        if details is None:
            return {}
        if not isinstance(details, Mapping):
            raise TypeError("Audit details must be a mapping")
        return dict(details)

    @staticmethod
    def _normalize_timestamp(timestamp: datetime) -> datetime:
        if not isinstance(timestamp, datetime):
            raise TypeError("Audit clock must return a datetime")
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
