"""Client domain models."""

from collections.abc import Mapping
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes
from uuid import uuid4

from .enums import ClientStatus

_PASSWORD_HASH_ITERATIONS = 100_000


class Client:
    """A bank client with contact, account, and authentication state."""

    def __init__(
        self,
        full_name: str,
        age: int,
        contacts: Mapping[str, str],
        password: str,
        client_id: str | None = None,
        status: ClientStatus | str = ClientStatus.ACTIVE,
    ) -> None:
        self._full_name = self._validate_full_name(full_name)
        self._age = self._validate_age(age)
        self._contacts = self._validate_contacts(contacts)
        self._client_id = self._validate_client_id(client_id)
        self._status = self._validate_status(status)
        self._account_numbers: list[str] = []
        self._failed_authentication_attempts = 0
        self._suspicious_activity = False

        normalized_password = self._validate_password(password)
        self._password_salt = token_bytes(16)
        self._password_digest = self._hash_password(normalized_password)

    @property
    def full_name(self) -> str:
        """Return the client's full name."""

        return self._full_name

    @property
    def age(self) -> int:
        """Return the client's age."""

        return self._age

    @property
    def client_id(self) -> str:
        """Return the client identifier."""

        return self._client_id

    @property
    def status(self) -> ClientStatus:
        """Return the client's access status."""

        return self._status

    @property
    def contacts(self) -> dict[str, str]:
        """Return a copy of the client's contacts."""

        return dict(self._contacts)

    @property
    def account_numbers(self) -> list[str]:
        """Return a copy of the client's account numbers."""

        return list(self._account_numbers)

    @property
    def failed_authentication_attempts(self) -> int:
        """Return the number of consecutive failed authentication attempts."""

        return self._failed_authentication_attempts

    @property
    def suspicious_activity(self) -> bool:
        """Return whether suspicious activity has been detected for the client."""

        return self._suspicious_activity

    def _verify_password(self, password: str) -> bool:
        if not isinstance(password, str):
            raise TypeError("Password must be a string")
        return compare_digest(self._password_digest, self._hash_password(password))

    def _record_failed_authentication(self) -> int:
        self._failed_authentication_attempts += 1
        return self._failed_authentication_attempts

    def _reset_failed_authentication(self) -> None:
        self._failed_authentication_attempts = 0

    def _block(self) -> None:
        self._status = ClientStatus.BLOCKED
        self._suspicious_activity = True

    def _mark_suspicious(self) -> None:
        self._suspicious_activity = True

    def _add_account_number(self, account_number: str) -> None:
        if account_number not in self._account_numbers:
            self._account_numbers.append(account_number)

    def _hash_password(self, password: str) -> bytes:
        return pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            self._password_salt,
            _PASSWORD_HASH_ITERATIONS,
        )

    @staticmethod
    def _validate_full_name(full_name: str) -> str:
        if not isinstance(full_name, str):
            raise TypeError("Full name must be a string")

        normalized_name = full_name.strip()
        if not normalized_name:
            raise ValueError("Full name must not be empty")

        return normalized_name

    @staticmethod
    def _validate_age(age: int) -> int:
        if isinstance(age, bool) or not isinstance(age, int):
            raise TypeError("Age must be an integer")
        if age < 18:
            raise ValueError("Client must be at least 18 years old")

        return age

    @staticmethod
    def _validate_client_id(client_id: str | None) -> str:
        if client_id is None:
            return uuid4().hex[:8]
        if not isinstance(client_id, str):
            raise TypeError("Client identifier must be a string")

        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise ValueError("Client identifier must not be empty")

        return normalized_client_id

    @staticmethod
    def _validate_status(status: ClientStatus | str) -> ClientStatus:
        if isinstance(status, ClientStatus):
            return status
        if isinstance(status, str):
            try:
                return ClientStatus(status.strip().lower())
            except ValueError:
                pass

        allowed_statuses = ", ".join(item.value for item in ClientStatus)
        raise ValueError(f"Status must be one of: {allowed_statuses}")

    @staticmethod
    def _validate_contacts(contacts: Mapping[str, str]) -> dict[str, str]:
        if not isinstance(contacts, Mapping):
            raise TypeError("Contacts must be a mapping")
        if not contacts:
            raise ValueError("Contacts must not be empty")

        normalized_contacts: dict[str, str] = {}
        for kind, value in contacts.items():
            if not isinstance(kind, str) or not isinstance(value, str):
                raise TypeError("Contact names and values must be strings")

            normalized_kind = kind.strip()
            normalized_value = value.strip()
            if not normalized_kind or not normalized_value:
                raise ValueError("Contact names and values must not be empty")
            if normalized_kind in normalized_contacts:
                raise ValueError(f"Contacts contain duplicate name: {normalized_kind}")

            normalized_contacts[normalized_kind] = normalized_value

        return normalized_contacts

    @staticmethod
    def _validate_password(password: str) -> str:
        if not isinstance(password, str):
            raise TypeError("Password must be a string")
        if not password:
            raise ValueError("Password must not be empty")

        return password
