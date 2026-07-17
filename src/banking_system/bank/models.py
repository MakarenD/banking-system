"""Bank orchestration models."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from banking_system.accounts import AccountStatus, BankAccount, InvalidOperationError
from banking_system.clients import Client, ClientStatus

from .exceptions import (
    AccountNotFoundError,
    ClientBlockedError,
    ClientNotFoundError,
    DuplicateAccountError,
    DuplicateClientError,
    RestrictedOperationError,
)

_MAX_AUTHENTICATION_ATTEMPTS = 3
_OPERATIONS_ALLOWED_FROM_HOUR = 5


class Bank:
    """Coordinate clients, accounts, authentication, and account lifecycle."""

    def __init__(
        self,
        name: str = "Bank",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.name = name
        self._clock = clock or datetime.now
        self._clients: dict[str, Client] = {}
        self._accounts: dict[str, BankAccount] = {}
        self._account_owners: dict[str, str] = {}

    @property
    def clients(self) -> tuple[Client, ...]:
        """Return an immutable snapshot of registered clients."""

        return tuple(self._clients.values())

    @property
    def accounts(self) -> tuple[BankAccount, ...]:
        """Return an immutable snapshot of registered accounts."""

        return tuple(self._accounts.values())

    def add_client(self, client: Client) -> Client:
        """Register and return a client."""

        if not isinstance(client, Client):
            raise TypeError("Client must be a Client instance")
        if client.client_id in self._clients:
            raise DuplicateClientError(f"Client is already registered: {client.client_id}")

        self._clients[client.client_id] = client
        return client

    def open_account(
        self,
        client_id: str,
        account_type: type[BankAccount] = BankAccount,
        **account_options: Any,
    ) -> BankAccount:
        """Create and register an active account for a client."""

        client = self._get_client(client_id)
        self._ensure_client_is_active(client)
        self._ensure_operations_allowed(client)
        self._validate_account_type(account_type)
        if "owner" in account_options:
            raise ValueError("Account owner is determined by the registered client")
        if "status" in account_options:
            raise ValueError("New accounts are opened in active status")

        account = account_type(
            owner=client.full_name,
            status=AccountStatus.ACTIVE,
            **account_options,
        )
        if account.account_number in self._accounts:
            raise DuplicateAccountError(f"Account is already registered: {account.account_number}")

        self._accounts[account.account_number] = account
        self._account_owners[account.account_number] = client.client_id
        client._add_account_number(account.account_number)
        return account

    def close_account(self, account_number: str) -> BankAccount:
        """Close an active or frozen account and return it."""

        account, client = self._get_account_and_client(account_number)
        self._ensure_client_is_active(client)
        self._ensure_operations_allowed(client)
        if account.status is AccountStatus.CLOSED:
            raise InvalidOperationError("Account is already closed")

        account._set_status(AccountStatus.CLOSED)
        return account

    def freeze_account(self, account_number: str) -> BankAccount:
        """Freeze an active account and return it."""

        account, client = self._get_account_and_client(account_number)
        self._ensure_client_is_active(client)
        self._ensure_operations_allowed(client)
        if account.status is not AccountStatus.ACTIVE:
            raise InvalidOperationError("Only an active account can be frozen")

        account._set_status(AccountStatus.FROZEN)
        return account

    def unfreeze_account(self, account_number: str) -> BankAccount:
        """Restore a frozen account to active status and return it."""

        account, client = self._get_account_and_client(account_number)
        self._ensure_client_is_active(client)
        self._ensure_operations_allowed(client)
        if account.status is not AccountStatus.FROZEN:
            raise InvalidOperationError("Only a frozen account can be unfrozen")

        account._set_status(AccountStatus.ACTIVE)
        return account

    def authenticate_client(self, client_id: str, password: str) -> bool:
        """Authenticate a client and apply the consecutive-failure limit."""

        client = self._clients.get(client_id.strip()) if isinstance(client_id, str) else None
        if client is None or client.status is ClientStatus.BLOCKED:
            return False
        if client._verify_password(password):
            client._reset_failed_authentication()
            return True

        attempts = client._record_failed_authentication()
        if attempts >= _MAX_AUTHENTICATION_ATTEMPTS:
            client._block()
        return False

    def search_accounts(self, query: str) -> list[BankAccount]:
        """Find accounts by number or client name using a case-insensitive substring."""

        if not isinstance(query, str):
            raise TypeError("Search query must be a string")

        normalized_query = query.strip().casefold()
        if not normalized_query:
            return []

        matches = []
        for account_number, account in self._accounts.items():
            client = self._clients[self._account_owners[account_number]]
            if (
                normalized_query in account_number.casefold()
                or normalized_query in client.full_name.casefold()
            ):
                matches.append(account)

        return sorted(matches, key=lambda account: account.account_number.casefold())

    def get_client(self, client_id: str) -> Client:
        """Return a registered client or raise ``ClientNotFoundError``."""

        return self._get_client(client_id)

    def get_account(self, account_number: str) -> BankAccount:
        """Return a registered account or raise ``AccountNotFoundError``."""

        account, _ = self._get_account_and_client(account_number)
        return account

    def get_client_accounts(self, client_id: str) -> tuple[BankAccount, ...]:
        """Return accounts owned by a registered client."""

        client = self._get_client(client_id)
        return tuple(
            account
            for account_number, account in self._accounts.items()
            if self._account_owners[account_number] == client.client_id
        )

    def get_account_owner(self, account_number: str) -> Client:
        """Return the client who owns a registered account."""

        _, client = self._get_account_and_client(account_number)
        return client

    def get_total_balance(self) -> Decimal:
        """Return the nominal total of all registered account balances."""

        return sum((account.balance for account in self._accounts.values()), Decimal("0"))

    def get_clients_ranking(self) -> list[tuple[Client, Decimal]]:
        """Return clients and nominal balances ordered from highest to lowest."""

        balances = dict.fromkeys(self._clients, Decimal("0"))
        for account_number, account in self._accounts.items():
            client_id = self._account_owners[account_number]
            balances[client_id] += account.balance

        return [
            (self._clients[client_id], total)
            for client_id, total in sorted(
                balances.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def _get_client(self, client_id: str) -> Client:
        if not isinstance(client_id, str):
            raise TypeError("Client identifier must be a string")

        normalized_client_id = client_id.strip()
        try:
            return self._clients[normalized_client_id]
        except KeyError as error:
            raise ClientNotFoundError(f"Client was not found: {normalized_client_id}") from error

    def _get_account_and_client(self, account_number: str) -> tuple[BankAccount, Client]:
        if not isinstance(account_number, str):
            raise TypeError("Account number must be a string")

        normalized_account_number = account_number.strip()
        try:
            account = self._accounts[normalized_account_number]
        except KeyError as error:
            raise AccountNotFoundError(
                f"Account was not found: {normalized_account_number}"
            ) from error

        client_id = self._account_owners[normalized_account_number]
        return account, self._clients[client_id]

    def _ensure_client_is_active(self, client: Client) -> None:
        if client.status is ClientStatus.BLOCKED:
            raise ClientBlockedError(f"Client is blocked: {client.client_id}")

    def _ensure_operations_allowed(self, client: Client) -> None:
        if self._clock().hour < _OPERATIONS_ALLOWED_FROM_HOUR:
            client._mark_suspicious()
            raise RestrictedOperationError("Account operations are unavailable from 00:00 to 05:00")

    @staticmethod
    def _validate_account_type(account_type: type[BankAccount]) -> None:
        if not isinstance(account_type, type) or not issubclass(account_type, BankAccount):
            raise TypeError("Account type must be a BankAccount subclass")
