"""Account domain models."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .enums import AccountStatus, Currency, InvestmentAsset
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


class SavingsAccount(BankAccount):
    """An interest-bearing account that preserves a minimum balance."""

    def __init__(
        self,
        owner: str,
        balance: Amount = 0,
        account_id: str | None = None,
        status: AccountStatus | str = AccountStatus.ACTIVE,
        currency: Currency | str = Currency.RUB,
        min_balance: Amount = 0,
        monthly_interest_rate: Amount = 0,
    ) -> None:
        super().__init__(owner, balance, account_id, status, currency)
        self._min_balance = self._validate_amount(min_balance, allow_zero=True)
        self._monthly_interest_rate = self._validate_amount(monthly_interest_rate, allow_zero=True)
        if self.balance < self.min_balance:
            raise InvalidOperationError("Initial balance must not be below the minimum balance")

    @property
    def min_balance(self) -> Decimal:
        """Return the balance that withdrawals must preserve."""

        return self._min_balance

    @property
    def monthly_interest_rate(self) -> Decimal:
        """Return the monthly interest rate as a decimal fraction."""

        return self._monthly_interest_rate

    def withdraw(self, amount: Amount) -> Decimal:
        """Withdraw funds while preserving the configured minimum balance."""

        self._ensure_active()
        normalized_amount = self._validate_amount(amount)
        if self.balance - normalized_amount < self.min_balance:
            raise InsufficientFundsError("Withdrawal would reduce balance below the minimum")

        self._balance -= normalized_amount
        return self._balance

    def apply_monthly_interest(self) -> Decimal:
        """Apply one month of interest and return the updated balance."""

        self._ensure_active()
        self._balance += self.balance * self.monthly_interest_rate
        return self._balance

    def get_account_info(self) -> dict[str, Any]:
        """Return the public savings account state."""

        info = super().get_account_info()
        info.update(
            {
                "min_balance": self.min_balance,
                "monthly_interest_rate": self.monthly_interest_rate,
            }
        )
        return info

    def __str__(self) -> str:
        account_suffix = self.account_id[-4:]
        balance = format(self.balance, "f")
        min_balance = format(self.min_balance, "f")
        interest_rate = format(self.monthly_interest_rate, "f")
        return (
            f"SavingsAccount(owner={self.owner}, account=…{account_suffix}, "
            f"status={self.status.value}, balance={balance} {self.currency.value}, "
            f"min_balance={min_balance}, monthly_interest_rate={interest_rate})"
        )


class PremiumAccount(BankAccount):
    """An account with a high withdrawal limit and an overdraft facility."""

    def __init__(
        self,
        owner: str,
        balance: Amount = 0,
        account_id: str | None = None,
        status: AccountStatus | str = AccountStatus.ACTIVE,
        currency: Currency | str = Currency.RUB,
        withdrawal_limit: Amount = 1_000_000,
        overdraft_limit: Amount = 100_000,
        fixed_fee: Amount = 100,
    ) -> None:
        super().__init__(owner, balance, account_id, status, currency)
        self._withdrawal_limit = self._validate_amount(withdrawal_limit)
        self._overdraft_limit = self._validate_amount(overdraft_limit, allow_zero=True)
        self._fixed_fee = self._validate_amount(fixed_fee, allow_zero=True)

    @property
    def withdrawal_limit(self) -> Decimal:
        """Return the maximum amount allowed in one withdrawal."""

        return self._withdrawal_limit

    @property
    def overdraft_limit(self) -> Decimal:
        """Return the maximum permitted negative balance."""

        return self._overdraft_limit

    @property
    def fixed_fee(self) -> Decimal:
        """Return the fee charged for each withdrawal."""

        return self._fixed_fee

    def withdraw(self, amount: Amount) -> Decimal:
        """Withdraw an amount plus the fixed fee within premium limits."""

        self._ensure_active()
        normalized_amount = self._validate_amount(amount)
        if normalized_amount > self.withdrawal_limit:
            raise InvalidOperationError("Withdrawal limit exceeded")

        total_charge = normalized_amount + self.fixed_fee
        if total_charge > self.balance + self.overdraft_limit:
            raise InsufficientFundsError("Overdraft limit exceeded")

        self._balance -= total_charge
        return self._balance

    def get_account_info(self) -> dict[str, Any]:
        """Return the public premium account state."""

        info = super().get_account_info()
        info.update(
            {
                "withdrawal_limit": self.withdrawal_limit,
                "overdraft_limit": self.overdraft_limit,
                "fixed_fee": self.fixed_fee,
            }
        )
        return info

    def __str__(self) -> str:
        account_suffix = self.account_id[-4:]
        balance = format(self.balance, "f")
        withdrawal_limit = format(self.withdrawal_limit, "f")
        overdraft_limit = format(self.overdraft_limit, "f")
        fixed_fee = format(self.fixed_fee, "f")
        return (
            f"PremiumAccount(owner={self.owner}, account=…{account_suffix}, "
            f"status={self.status.value}, balance={balance} {self.currency.value}, "
            f"withdrawal_limit={withdrawal_limit}, overdraft_limit={overdraft_limit}, "
            f"fixed_fee={fixed_fee})"
        )


class InvestmentAccount(BankAccount):
    """An account with virtual asset positions and yearly growth projections."""

    def __init__(
        self,
        owner: str,
        balance: Amount = 0,
        account_id: str | None = None,
        status: AccountStatus | str = AccountStatus.ACTIVE,
        currency: Currency | str = Currency.RUB,
        portfolio: Mapping[InvestmentAsset | str, Amount] | None = None,
        yearly_growth_rates: Mapping[InvestmentAsset | str, Amount] | None = None,
    ) -> None:
        super().__init__(owner, balance, account_id, status, currency)
        self._portfolio = self._validate_portfolio(portfolio)
        self._yearly_growth_rates = self._validate_growth_rates(
            yearly_growth_rates, self._portfolio
        )

    @property
    def portfolio(self) -> dict[str, Decimal]:
        """Return a copy of the virtual asset positions."""

        return {asset.value: value for asset, value in self._portfolio.items()}

    @property
    def yearly_growth_rates(self) -> dict[str, Decimal]:
        """Return configured yearly rates as decimal fractions."""

        return {asset.value: rate for asset, rate in self._yearly_growth_rates.items()}

    def withdraw(self, amount: Amount) -> Decimal:
        """Withdraw available cash without modifying virtual asset positions."""

        return super().withdraw(amount)

    def project_yearly_growth(self) -> Decimal:
        """Return the projected yearly gain across all virtual asset positions."""

        return sum(
            (value * self._yearly_growth_rates[asset] for asset, value in self._portfolio.items()),
            start=Decimal("0"),
        )

    def get_account_info(self) -> dict[str, Any]:
        """Return the public investment account state."""

        info = super().get_account_info()
        info.update(
            {
                "portfolio": self.portfolio,
                "yearly_growth_rates": self.yearly_growth_rates,
            }
        )
        return info

    def __str__(self) -> str:
        account_suffix = self.account_id[-4:]
        balance = format(self.balance, "f")
        assets = ", ".join(asset.value for asset in self._portfolio) or "empty"
        return (
            f"InvestmentAccount(owner={self.owner}, account=…{account_suffix}, "
            f"status={self.status.value}, balance={balance} {self.currency.value}, "
            f"portfolio={assets})"
        )

    @classmethod
    def _validate_portfolio(
        cls, portfolio: Mapping[InvestmentAsset | str, Amount] | None
    ) -> dict[InvestmentAsset, Decimal]:
        if portfolio is None:
            return {}
        if not isinstance(portfolio, Mapping):
            raise TypeError("Portfolio must be a mapping")

        normalized_portfolio: dict[InvestmentAsset, Decimal] = {}
        for asset, value in portfolio.items():
            normalized_asset = cls._validate_asset(asset)
            if normalized_asset in normalized_portfolio:
                raise ValueError(f"Portfolio contains duplicate asset: {normalized_asset.value}")
            normalized_portfolio[normalized_asset] = cls._validate_amount(value, allow_zero=True)

        return normalized_portfolio

    @classmethod
    def _validate_growth_rates(
        cls,
        rates: Mapping[InvestmentAsset | str, Amount] | None,
        portfolio: Mapping[InvestmentAsset, Decimal],
    ) -> dict[InvestmentAsset, Decimal]:
        if rates is None:
            return dict.fromkeys(portfolio, Decimal("0"))
        if not isinstance(rates, Mapping):
            raise TypeError("Yearly growth rates must be a mapping")

        normalized_rates: dict[InvestmentAsset, Decimal] = {}
        for asset, rate in rates.items():
            normalized_asset = cls._validate_asset(asset)
            if normalized_asset in normalized_rates:
                raise ValueError(
                    f"Yearly growth rates contain duplicate asset: {normalized_asset.value}"
                )
            normalized_rates[normalized_asset] = cls._validate_growth_rate(rate)

        unsupported_rates = normalized_rates.keys() - portfolio.keys()
        if unsupported_rates:
            names = ", ".join(sorted(asset.value for asset in unsupported_rates))
            raise ValueError(f"Growth rates require matching portfolio positions: {names}")

        return {asset: normalized_rates.get(asset, Decimal("0")) for asset in portfolio}

    @staticmethod
    def _validate_asset(asset: InvestmentAsset | str) -> InvestmentAsset:
        if isinstance(asset, InvestmentAsset):
            return asset
        if isinstance(asset, str):
            try:
                return InvestmentAsset(asset.strip().lower())
            except ValueError:
                pass

        allowed_assets = ", ".join(item.value for item in InvestmentAsset)
        raise ValueError(f"Asset must be one of: {allowed_assets}")

    @staticmethod
    def _validate_growth_rate(rate: Amount) -> Decimal:
        if isinstance(rate, bool) or not isinstance(rate, (int, float, Decimal)):
            raise InvalidOperationError("Growth rate must be a number")

        normalized_rate = Decimal(str(rate))
        if not normalized_rate.is_finite():
            raise InvalidOperationError("Growth rate must be finite")
        if normalized_rate < -1:
            raise InvalidOperationError("Growth rate must not be less than -1")

        return normalized_rate
