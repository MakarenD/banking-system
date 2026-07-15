from decimal import Decimal

import pytest

from banking_system.accounts import (
    AbstractAccount,
    AccountClosedError,
    AccountFrozenError,
    AccountStatus,
    BankAccount,
    Currency,
    InsufficientFundsError,
    InvalidOperationError,
)


def test_abstract_account_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        AbstractAccount("Alice")  # type: ignore[abstract]


def test_bank_account_is_a_concrete_account() -> None:
    account = BankAccount("Alice")

    assert isinstance(account, AbstractAccount)


def test_account_uses_provided_identifier() -> None:
    account = BankAccount("Alice", account_id="  account-1234  ")

    assert account.account_id == "account-1234"
    assert account.account_number == "account-1234"


def test_account_generates_unique_short_uuid_identifiers() -> None:
    first_account = BankAccount("Alice")
    second_account = BankAccount("Bob")

    assert len(first_account.account_id) == 8
    assert all(character in "0123456789abcdef" for character in first_account.account_id)
    assert first_account.account_id != second_account.account_id


@pytest.mark.parametrize("owner", ["", "   "])
def test_account_rejects_empty_owner(owner: str) -> None:
    with pytest.raises(ValueError):
        BankAccount(owner)


@pytest.mark.parametrize("owner", [None, 42, True])
def test_account_rejects_non_string_owner(owner: object) -> None:
    with pytest.raises(TypeError):
        BankAccount(owner)  # type: ignore[arg-type]


@pytest.mark.parametrize("account_id", ["", "   "])
def test_account_rejects_empty_identifier(account_id: str) -> None:
    with pytest.raises(ValueError):
        BankAccount("Alice", account_id=account_id)


def test_account_rejects_non_string_identifier() -> None:
    with pytest.raises(TypeError):
        BankAccount("Alice", account_id=1234)  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", list(Currency))
def test_account_supports_declared_currencies(currency: Currency) -> None:
    account = BankAccount("Alice", currency=currency.value.lower())

    assert account.currency is currency


def test_account_rejects_unsupported_currency() -> None:
    with pytest.raises(ValueError, match="Currency must be one of"):
        BankAccount("Alice", currency="GBP")


@pytest.mark.parametrize("status", list(AccountStatus))
def test_account_supports_declared_statuses(status: AccountStatus) -> None:
    account = BankAccount("Alice", status=status.value.upper())

    assert account.status is status


def test_account_rejects_unsupported_status() -> None:
    with pytest.raises(ValueError, match="Status must be one of"):
        BankAccount("Alice", status="pending")


@pytest.mark.parametrize("balance", [-1, True, "100", float("nan"), float("inf")])
def test_account_rejects_invalid_initial_balance(balance: object) -> None:
    with pytest.raises(InvalidOperationError):
        BankAccount("Alice", balance=balance)  # type: ignore[arg-type]


def test_balance_is_read_only() -> None:
    account = BankAccount("Alice", balance=100)

    with pytest.raises(AttributeError):
        account.balance = Decimal("200")  # type: ignore[misc]


def test_deposit_increases_balance_and_returns_updated_value() -> None:
    account = BankAccount("Alice", balance=Decimal("100.25"))

    updated_balance = account.deposit(49.75)

    assert updated_balance == Decimal("150.00")
    assert account.balance == Decimal("150.00")


def test_withdraw_decreases_balance_and_returns_updated_value() -> None:
    account = BankAccount("Alice", balance=100)

    updated_balance = account.withdraw(Decimal("40.50"))

    assert updated_balance == Decimal("59.50")
    assert account.balance == Decimal("59.50")


def test_withdraw_all_funds_leaves_zero_balance() -> None:
    account = BankAccount("Alice", balance=100)

    assert account.withdraw(100) == Decimal("0")


@pytest.mark.parametrize(
    "operation_name, amount",
    [
        ("deposit", 0),
        ("deposit", -1),
        ("deposit", True),
        ("deposit", "10"),
        ("deposit", float("nan")),
        ("withdraw", 0),
        ("withdraw", -1),
        ("withdraw", True),
        ("withdraw", "10"),
        ("withdraw", float("inf")),
    ],
)
def test_operations_reject_invalid_amounts_without_changing_balance(
    operation_name: str, amount: object
) -> None:
    account = BankAccount("Alice", balance=100)
    operation = getattr(account, operation_name)

    with pytest.raises(InvalidOperationError):
        operation(amount)

    assert account.balance == Decimal("100")


@pytest.mark.parametrize(
    "status, error_type",
    [
        (AccountStatus.FROZEN, AccountFrozenError),
        (AccountStatus.CLOSED, AccountClosedError),
    ],
)
@pytest.mark.parametrize("operation_name", ["deposit", "withdraw"])
def test_inactive_account_rejects_operations_without_changing_balance(
    status: AccountStatus,
    error_type: type[InvalidOperationError],
    operation_name: str,
) -> None:
    account = BankAccount("Alice", balance=100, status=status)
    operation = getattr(account, operation_name)

    with pytest.raises(error_type):
        operation(10)

    assert account.balance == Decimal("100")


def test_withdraw_rejects_insufficient_funds_without_changing_balance() -> None:
    account = BankAccount("Alice", balance=100)

    with pytest.raises(InsufficientFundsError):
        account.withdraw(100.01)

    assert account.balance == Decimal("100")


def test_get_account_info_returns_public_state() -> None:
    account = BankAccount(
        "Alice",
        balance=Decimal("125.50"),
        account_id="account-1234",
        currency=Currency.USD,
    )

    assert account.get_account_info() == {
        "account_type": "BankAccount",
        "account_id": "account-1234",
        "owner": "Alice",
        "status": "active",
        "balance": Decimal("125.50"),
        "currency": "USD",
    }


def test_string_representation_contains_required_details_and_masks_identifier() -> None:
    account = BankAccount(
        "Alice",
        balance=Decimal("125.50"),
        account_id="account-1234",
        status=AccountStatus.FROZEN,
        currency=Currency.EUR,
    )

    representation = str(account)

    assert "BankAccount" in representation
    assert "Alice" in representation
    assert "1234" in representation
    assert "account-1234" not in representation
    assert "frozen" in representation
    assert "125.50 EUR" in representation
