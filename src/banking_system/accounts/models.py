"""Account domain models."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .enums import AccountStatus, Currency
from .exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)

Amount = int | float | Decimal


class AbstractAccount(ABC):
    """Common state and interface for account implementations."""

    def __init__(
        self,
        owner: str,
        balance: Amount = 0,
        account_id: str | None = None,
        status: AccountStatus | str = AccountStatus.ACTIVE,
    ) -> None:
        self._owner = self._validate_owner(owner)
        self._account_id = self._validate_account_id(account_id)
        self._balance = self._validate_amount(balance, allow_zero=True)
        self._status = self._validate_status(status)

    @property
    def account_id(self) -> str:
        """Return the account identifier."""

        return self._account_id

    @property
    def account_number(self) -> str:
        """Return the account identifier using banking terminology."""

        return self._account_id

    @property
    def owner(self) -> str:
        """Return the account owner's name."""

        return self._owner

    @property
    def balance(self) -> Decimal:
        """Return the current balance."""

        return self._balance

    @property
    def status(self) -> AccountStatus:
        """Return the current account status."""

        return self._status

    @abstractmethod
    def deposit(self, amount: Amount) -> Decimal:
        """Deposit funds and return the updated balance."""

    @abstractmethod
    def withdraw(self, amount: Amount) -> Decimal:
        """Withdraw funds and return the updated balance."""

    @abstractmethod
    def get_account_info(self) -> dict[str, Any]:
        """Return account details as a mapping."""

    @staticmethod
    def _validate_owner(owner: str) -> str:
        if not isinstance(owner, str):
            raise TypeError("Owner must be a string")

        normalized_owner = owner.strip()
        if not normalized_owner:
            raise ValueError("Owner must not be empty")

        return normalized_owner

    @staticmethod
    def _validate_account_id(account_id: str | None) -> str:
        if account_id is None:
            return uuid4().hex[:8]
        if not isinstance(account_id, str):
            raise TypeError("Account identifier must be a string")

        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            raise ValueError("Account identifier must not be empty")

        return normalized_account_id

    @staticmethod
    def _validate_status(status: AccountStatus | str) -> AccountStatus:
        if isinstance(status, AccountStatus):
            return status
        if isinstance(status, str):
            try:
                return AccountStatus(status.strip().lower())
            except ValueError:
                pass

        allowed_statuses = ", ".join(item.value for item in AccountStatus)
        raise ValueError(f"Status must be one of: {allowed_statuses}")

    @staticmethod
    def _validate_amount(amount: Amount, *, allow_zero: bool = False) -> Decimal:
        if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
            raise InvalidOperationError("Amount must be a number")

        normalized_amount = Decimal(str(amount))
        if not normalized_amount.is_finite():
            raise InvalidOperationError("Amount must be finite")
        if normalized_amount < 0:
            raise InvalidOperationError("Amount must not be negative")
        if normalized_amount == 0 and not allow_zero:
            raise InvalidOperationError("Amount must be greater than zero")

        return normalized_amount


class BankAccount(AbstractAccount):
    """A bank account that supports deposits and withdrawals."""

    def __init__(
        self,
        owner: str,
        balance: Amount = 0,
        account_id: str | None = None,
        status: AccountStatus | str = AccountStatus.ACTIVE,
        currency: Currency | str = Currency.RUB,
    ) -> None:
        super().__init__(owner, balance, account_id, status)
        self._currency = self._validate_currency(currency)

    @property
    def currency(self) -> Currency:
        """Return the account currency."""

        return self._currency

    def deposit(self, amount: Amount) -> Decimal:
        """Deposit a positive amount into an active account."""

        self._ensure_active()
        self._balance += self._validate_amount(amount)
        return self._balance

    def withdraw(self, amount: Amount) -> Decimal:
        """Withdraw a positive amount from an active account."""

        self._ensure_active()
        normalized_amount = self._validate_amount(amount)
        if normalized_amount > self._balance:
            raise InsufficientFundsError("Insufficient funds")

        self._balance -= normalized_amount
        return self._balance

    def get_account_info(self) -> dict[str, Any]:
        """Return the public account state."""

        return {
            "account_type": type(self).__name__,
            "account_id": self.account_id,
            "owner": self.owner,
            "status": self.status.value,
            "balance": self.balance,
            "currency": self.currency.value,
        }

    def __str__(self) -> str:
        account_suffix = self.account_id[-4:]
        balance = format(self.balance, "f")
        return (
            f"{type(self).__name__}(owner={self.owner}, account=…{account_suffix}, "
            f"status={self.status.value}, balance={balance} {self.currency.value})"
        )

    def _ensure_active(self) -> None:
        if self.status is AccountStatus.FROZEN:
            raise AccountFrozenError("Account is frozen")
        if self.status is AccountStatus.CLOSED:
            raise AccountClosedError("Account is closed")

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
