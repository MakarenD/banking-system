from decimal import Decimal

import pytest

from banking_system.accounts import (
    AbstractAccount,
    AccountClosedError,
    AccountFrozenError,
    AccountStatus,
    BankAccount,
    InsufficientFundsError,
    InvalidOperationError,
    InvestmentAccount,
    InvestmentAsset,
    PremiumAccount,
    SavingsAccount,
)


@pytest.mark.parametrize(
    "account_type",
    [SavingsAccount, PremiumAccount, InvestmentAccount],
)
def test_advanced_accounts_are_concrete_bank_accounts(
    account_type: type[BankAccount],
) -> None:
    account = account_type("Alice")

    assert isinstance(account, BankAccount)
    assert isinstance(account, AbstractAccount)


@pytest.mark.parametrize(
    "account_type",
    [SavingsAccount, PremiumAccount, InvestmentAccount],
)
@pytest.mark.parametrize("method_name", ["withdraw", "get_account_info", "__str__"])
def test_advanced_accounts_override_polymorphic_methods(
    account_type: type[BankAccount], method_name: str
) -> None:
    assert method_name in account_type.__dict__


def test_savings_account_applies_monthly_interest() -> None:
    account = SavingsAccount("Alice", balance=1_000, monthly_interest_rate=Decimal("0.015"))

    updated_balance = account.apply_monthly_interest()

    assert updated_balance == Decimal("1015.000")
    assert account.balance == Decimal("1015.000")


def test_savings_account_preserves_minimum_balance() -> None:
    account = SavingsAccount("Alice", balance=1_000, min_balance=250)

    assert account.withdraw(750) == Decimal("250")

    with pytest.raises(InsufficientFundsError, match="below the minimum"):
        account.withdraw(Decimal("0.01"))

    assert account.balance == Decimal("250")


def test_savings_account_rejects_initial_balance_below_minimum() -> None:
    with pytest.raises(InvalidOperationError, match="Initial balance"):
        SavingsAccount("Alice", balance=99, min_balance=100)


@pytest.mark.parametrize(
    "field, value",
    [
        ("min_balance", -1),
        ("monthly_interest_rate", -0.01),
        ("monthly_interest_rate", float("inf")),
    ],
)
def test_savings_account_rejects_invalid_configuration(field: str, value: object) -> None:
    with pytest.raises(InvalidOperationError):
        SavingsAccount("Alice", **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "status, error_type",
    [
        (AccountStatus.FROZEN, AccountFrozenError),
        (AccountStatus.CLOSED, AccountClosedError),
    ],
)
def test_inactive_savings_account_rejects_interest(
    status: AccountStatus, error_type: type[InvalidOperationError]
) -> None:
    account = SavingsAccount("Alice", balance=1_000, monthly_interest_rate=0.01, status=status)

    with pytest.raises(error_type):
        account.apply_monthly_interest()

    assert account.balance == Decimal("1000")


def test_savings_account_exposes_specialized_public_state() -> None:
    account = SavingsAccount(
        "Alice",
        balance=1_000,
        account_id="savings-1234",
        min_balance=250,
        monthly_interest_rate=0.01,
    )

    info = account.get_account_info()
    representation = str(account)

    assert info["account_type"] == "SavingsAccount"
    assert info["min_balance"] == Decimal("250")
    assert info["monthly_interest_rate"] == Decimal("0.01")
    assert "SavingsAccount" in representation
    assert "min_balance=250" in representation
    assert "monthly_interest_rate=0.01" in representation
    assert "1234" in representation
    assert "savings-1234" not in representation


def test_premium_account_charges_fee_and_uses_overdraft() -> None:
    account = PremiumAccount(
        "Alice",
        balance=100,
        withdrawal_limit=150,
        overdraft_limit=60,
        fixed_fee=10,
    )

    updated_balance = account.withdraw(150)

    assert updated_balance == Decimal("-60")
    assert account.balance == Decimal("-60")


def test_premium_account_rejects_withdrawal_above_transaction_limit() -> None:
    account = PremiumAccount(
        "Alice",
        balance=10_000,
        withdrawal_limit=1_000,
        overdraft_limit=500,
        fixed_fee=10,
    )

    with pytest.raises(InvalidOperationError, match="Withdrawal limit"):
        account.withdraw(Decimal("1000.01"))

    assert account.balance == Decimal("10000")


def test_premium_account_rejects_charge_above_overdraft_limit() -> None:
    account = PremiumAccount(
        "Alice",
        balance=100,
        withdrawal_limit=1_000,
        overdraft_limit=50,
        fixed_fee=10,
    )

    with pytest.raises(InsufficientFundsError, match="Overdraft limit"):
        account.withdraw(150)

    assert account.balance == Decimal("100")


@pytest.mark.parametrize(
    "field, value",
    [
        ("withdrawal_limit", 0),
        ("withdrawal_limit", -1),
        ("overdraft_limit", -1),
        ("fixed_fee", -1),
        ("fixed_fee", float("nan")),
    ],
)
def test_premium_account_rejects_invalid_limits_and_fee(field: str, value: object) -> None:
    with pytest.raises(InvalidOperationError):
        PremiumAccount("Alice", **{field: value})  # type: ignore[arg-type]


def test_premium_account_exposes_specialized_public_state() -> None:
    account = PremiumAccount(
        "Alice",
        balance=500,
        account_id="premium-1234",
        withdrawal_limit=10_000,
        overdraft_limit=2_000,
        fixed_fee=25,
    )

    info = account.get_account_info()
    representation = str(account)

    assert info["account_type"] == "PremiumAccount"
    assert info["withdrawal_limit"] == Decimal("10000")
    assert info["overdraft_limit"] == Decimal("2000")
    assert info["fixed_fee"] == Decimal("25")
    assert "PremiumAccount" in representation
    assert "withdrawal_limit=10000" in representation
    assert "overdraft_limit=2000" in representation
    assert "fixed_fee=25" in representation
    assert "1234" in representation
    assert "premium-1234" not in representation


def test_investment_account_normalizes_supported_portfolio_assets() -> None:
    source_portfolio = {" STOCKS ": 1_000, InvestmentAsset.BONDS: Decimal("500.50")}
    account = InvestmentAccount("Alice", portfolio=source_portfolio)

    source_portfolio[" STOCKS "] = 0
    returned_portfolio = account.portfolio
    returned_portfolio["stocks"] = Decimal("0")

    assert account.portfolio == {
        "stocks": Decimal("1000"),
        "bonds": Decimal("500.50"),
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("portfolio", ["stocks"]),
        ("yearly_growth_rates", [0.1]),
    ],
)
def test_investment_account_requires_mapping_configuration(field: str, value: object) -> None:
    configuration: dict[str, object] = {"portfolio": {"stocks": 1_000}}
    configuration[field] = value

    with pytest.raises(TypeError, match="mapping"):
        InvestmentAccount("Alice", **configuration)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "portfolio, yearly_growth_rates, error_message",
    [
        (
            {"stocks": 100, " STOCKS ": 900},
            None,
            "Portfolio contains duplicate asset: stocks",
        ),
        (
            {"stocks": 1_000},
            {"stocks": 0.1, " STOCKS ": 0.2},
            "Yearly growth rates contain duplicate asset: stocks",
        ),
    ],
)
def test_investment_account_rejects_duplicate_normalized_assets(
    portfolio: dict[str, int],
    yearly_growth_rates: dict[str, float] | None,
    error_message: str,
) -> None:
    with pytest.raises(ValueError, match=error_message):
        InvestmentAccount(
            "Alice",
            portfolio=portfolio,
            yearly_growth_rates=yearly_growth_rates,
        )


@pytest.mark.parametrize("asset", ["crypto", "gold", ""])
def test_investment_account_rejects_unsupported_assets(asset: str) -> None:
    with pytest.raises(ValueError, match="Asset must be one of"):
        InvestmentAccount("Alice", portfolio={asset: 100})


@pytest.mark.parametrize("value", [-1, True, "100", float("nan")])
def test_investment_account_rejects_invalid_position_values(value: object) -> None:
    with pytest.raises(InvalidOperationError):
        InvestmentAccount("Alice", portfolio={"stocks": value})  # type: ignore[dict-item]


def test_investment_account_requires_rates_to_match_portfolio() -> None:
    with pytest.raises(ValueError, match="matching portfolio positions: bonds"):
        InvestmentAccount(
            "Alice",
            portfolio={"stocks": 1_000},
            yearly_growth_rates={"stocks": 0.1, "bonds": 0.05},
        )


@pytest.mark.parametrize("rate", [-1.01, True, "0.1", float("inf")])
def test_investment_account_rejects_invalid_growth_rates(rate: object) -> None:
    with pytest.raises(InvalidOperationError):
        InvestmentAccount(
            "Alice",
            portfolio={"stocks": 1_000},
            yearly_growth_rates={"stocks": rate},  # type: ignore[dict-item]
        )


def test_investment_account_projects_yearly_growth_for_portfolio() -> None:
    account = InvestmentAccount(
        "Alice",
        portfolio={"stocks": 1_000, "bonds": 500, "etf": 250},
        yearly_growth_rates={"stocks": 0.1, "bonds": 0.05, "etf": -0.2},
    )

    assert account.project_yearly_growth() == Decimal("75.00")


def test_investment_account_defaults_missing_growth_rate_to_zero() -> None:
    account = InvestmentAccount(
        "Alice",
        portfolio={"stocks": 1_000, "bonds": 500},
        yearly_growth_rates={"stocks": 0.1},
    )

    assert account.yearly_growth_rates == {
        "stocks": Decimal("0.1"),
        "bonds": Decimal("0"),
    }
    assert account.project_yearly_growth() == Decimal("100.0")


def test_investment_withdrawal_changes_only_cash_balance() -> None:
    account = InvestmentAccount(
        "Alice",
        balance=500,
        portfolio={"stocks": 1_000},
        yearly_growth_rates={"stocks": 0.1},
    )

    original_portfolio = account.portfolio

    assert account.withdraw(200) == Decimal("300")
    assert account.portfolio == original_portfolio


def test_investment_account_exposes_specialized_public_state() -> None:
    account = InvestmentAccount(
        "Alice",
        balance=500,
        account_id="investment-1234",
        portfolio={"stocks": 1_000, "etf": 250},
        yearly_growth_rates={"stocks": 0.1, "etf": 0.05},
    )

    info = account.get_account_info()
    representation = str(account)

    assert info["account_type"] == "InvestmentAccount"
    assert info["portfolio"] == {
        "stocks": Decimal("1000"),
        "etf": Decimal("250"),
    }
    assert info["yearly_growth_rates"] == {
        "stocks": Decimal("0.1"),
        "etf": Decimal("0.05"),
    }
    assert "InvestmentAccount" in representation
    assert "portfolio=stocks, etf" in representation
    assert "1234" in representation
    assert "investment-1234" not in representation
