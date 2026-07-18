from datetime import datetime
from decimal import Decimal

import pytest

from banking_system.accounts import (
    AccountStatus,
    BankAccount,
    Currency,
    InvalidOperationError,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
)
from banking_system.bank import (
    AccountNotFoundError,
    Bank,
    ClientBlockedError,
    ClientNotFoundError,
    DuplicateAccountError,
    DuplicateClientError,
    RestrictedOperationError,
)
from banking_system.clients import Client, ClientStatus


def make_client(
    client_id: str = "client-1",
    full_name: str = "Alice Smith",
    password: str = "correct-password",
) -> Client:
    return Client(
        full_name,
        30,
        {"email": f"{client_id}@example.com"},
        password,
        client_id=client_id,
    )


def make_bank(hour: int = 12, minute: int = 0) -> Bank:
    return Bank(clock=lambda: datetime(2026, 7, 15, hour, minute))


def test_bank_registers_client_and_rejects_duplicate_identifier() -> None:
    bank = make_bank()
    original = make_client()

    assert bank.add_client(original) is original

    with pytest.raises(DuplicateClientError, match="already registered"):
        bank.add_client(make_client(full_name="Another Person"))

    account = bank.open_account(original.client_id)
    assert account.owner == original.full_name


def test_bank_requires_client_instances() -> None:
    with pytest.raises(TypeError, match="Client instance"):
        make_bank().add_client("Alice")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "account_type",
    [BankAccount, SavingsAccount, PremiumAccount, InvestmentAccount],
)
def test_bank_opens_supported_account_types(account_type: type[BankAccount]) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    account = bank.open_account(
        client.client_id,
        account_type,
        account_id=f"{account_type.__name__}-1",
        balance=100,
    )

    assert type(account) is account_type
    assert account.owner == client.full_name
    assert account.status is AccountStatus.ACTIVE
    assert client.account_numbers == [account.account_number]
    assert bank.search_accounts(account.account_number) == [account]


def test_bank_rejects_unknown_or_blocked_client_without_opening_account() -> None:
    bank = make_bank()

    with pytest.raises(ClientNotFoundError):
        bank.open_account("missing-client")

    client = bank.add_client(make_client())
    for _ in range(3):
        assert bank.authenticate_client(client.client_id, "wrong-password") is False

    with pytest.raises(ClientBlockedError):
        bank.open_account(client.client_id)

    assert client.account_numbers == []


def test_bank_rejects_duplicate_account_number_without_mutating_client_links() -> None:
    bank = make_bank()
    first_client = bank.add_client(make_client())
    second_client = bank.add_client(make_client("client-2", "Bob Jones"))
    bank.open_account(first_client.client_id, account_id="shared-account")

    with pytest.raises(DuplicateAccountError, match="already registered"):
        bank.open_account(second_client.client_id, account_id="shared-account")

    assert first_client.account_numbers == ["shared-account"]
    assert second_client.account_numbers == []


@pytest.mark.parametrize(
    "account_type",
    [object, str, Bank],
)
def test_bank_rejects_unsupported_account_type(account_type: type[object]) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    with pytest.raises(TypeError, match="BankAccount subclass"):
        bank.open_account(client.client_id, account_type)  # type: ignore[arg-type]

    assert client.account_numbers == []


@pytest.mark.parametrize("reserved_option", ["owner", "status"])
def test_bank_controls_new_account_owner_and_status(reserved_option: str) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    with pytest.raises(ValueError):
        bank.open_account(client.client_id, **{reserved_option: "custom"})

    assert client.account_numbers == []


def test_bank_freezes_unfreezes_and_closes_account() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id, account_id="account-1")

    assert bank.freeze_account(account.account_number) is account
    assert account.status is AccountStatus.FROZEN
    assert bank.unfreeze_account(account.account_number) is account
    assert account.status is AccountStatus.ACTIVE
    assert bank.close_account(account.account_number) is account
    assert account.status is AccountStatus.CLOSED
    assert client.account_numbers == [account.account_number]
    assert bank.search_accounts("account-1") == [account]


def test_bank_can_close_frozen_account() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id)
    bank.freeze_account(account.account_number)

    bank.close_account(account.account_number)

    assert account.status is AccountStatus.CLOSED


def test_blocked_client_cannot_change_existing_account_state() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id)
    for _ in range(3):
        bank.authenticate_client(client.client_id, "wrong-password")

    with pytest.raises(ClientBlockedError):
        bank.freeze_account(account.account_number)

    assert account.status is AccountStatus.ACTIVE


@pytest.mark.parametrize(
    "initial_action, invalid_action, expected_status",
    [
        (None, "unfreeze_account", AccountStatus.ACTIVE),
        ("freeze_account", "freeze_account", AccountStatus.FROZEN),
        ("close_account", "close_account", AccountStatus.CLOSED),
        ("close_account", "freeze_account", AccountStatus.CLOSED),
        ("close_account", "unfreeze_account", AccountStatus.CLOSED),
    ],
)
def test_bank_rejects_invalid_account_state_transitions_without_mutation(
    initial_action: str | None,
    invalid_action: str,
    expected_status: AccountStatus,
) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id)
    if initial_action is not None:
        getattr(bank, initial_action)(account.account_number)

    with pytest.raises(InvalidOperationError):
        getattr(bank, invalid_action)(account.account_number)

    assert account.status is expected_status


@pytest.mark.parametrize(
    "operation_name",
    ["close_account", "freeze_account", "unfreeze_account"],
)
def test_account_lifecycle_operations_reject_unknown_account(operation_name: str) -> None:
    operation = getattr(make_bank(), operation_name)

    with pytest.raises(AccountNotFoundError, match="was not found"):
        operation("missing-account")


def test_authentication_succeeds_and_resets_consecutive_failures() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    assert bank.authenticate_client(client.client_id, "wrong-1") is False
    assert bank.authenticate_client(client.client_id, "wrong-2") is False
    assert client.failed_authentication_attempts == 2
    assert client.status is ClientStatus.ACTIVE
    assert client.suspicious_activity is False

    assert bank.authenticate_client(client.client_id, "correct-password") is True
    assert client.failed_authentication_attempts == 0

    assert bank.authenticate_client(client.client_id, "wrong-3") is False
    assert client.failed_authentication_attempts == 1
    assert client.status is ClientStatus.ACTIVE


def test_third_failed_authentication_blocks_and_marks_client() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    for _ in range(3):
        assert bank.authenticate_client(client.client_id, "wrong-password") is False

    assert client.failed_authentication_attempts == 3
    assert client.status is ClientStatus.BLOCKED
    assert client.suspicious_activity is True
    assert bank.authenticate_client(client.client_id, "correct-password") is False


def test_empty_password_counts_as_failed_authentication() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    for _ in range(3):
        assert bank.authenticate_client(client.client_id, "") is False

    assert client.status is ClientStatus.BLOCKED
    assert client.suspicious_activity is True


@pytest.mark.parametrize("password", [None, 123, True, b"password", object()])
def test_invalid_password_types_count_as_failed_authentication(password: object) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    for expected_attempts in range(1, 4):
        assert bank.authenticate_client(client.client_id, password) is False
        assert client.failed_authentication_attempts == expected_attempts

    assert client.status is ClientStatus.BLOCKED
    assert client.suspicious_activity is True
    assert bank.authenticate_client(client.client_id, "correct-password") is False


@pytest.mark.parametrize("failed_attempts", [1, 2])
def test_successful_authentication_resets_invalid_type_failures(failed_attempts: int) -> None:
    bank = make_bank()
    client = bank.add_client(make_client())

    for _ in range(failed_attempts):
        assert bank.authenticate_client(client.client_id, None) is False

    assert bank.authenticate_client(client.client_id, "correct-password") is True
    assert client.failed_authentication_attempts == 0
    assert client.status is ClientStatus.ACTIVE


def test_authentication_does_not_reveal_unknown_client() -> None:
    assert make_bank().authenticate_client("missing-client", "any-password") is False


@pytest.mark.parametrize("hour, minute", [(0, 0), (0, 1), (4, 59)])
def test_bank_rejects_account_opening_during_restricted_hours(hour: int, minute: int) -> None:
    bank = make_bank(hour, minute)
    client = bank.add_client(make_client())

    with pytest.raises(RestrictedOperationError, match="00:00 to 05:00"):
        bank.open_account(client.client_id)

    assert client.account_numbers == []
    assert client.suspicious_activity is True


@pytest.mark.parametrize(
    "operation_name, prepare_frozen",
    [
        ("close_account", False),
        ("freeze_account", False),
        ("unfreeze_account", True),
    ],
)
def test_restricted_lifecycle_operation_marks_client_without_changing_account(
    operation_name: str, prepare_frozen: bool
) -> None:
    current_time = [datetime(2026, 7, 15, 12, 0)]
    bank = Bank(clock=lambda: current_time[0])
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id)
    if prepare_frozen:
        bank.freeze_account(account.account_number)
    original_status = account.status
    current_time[0] = datetime(2026, 7, 16, 4, 59)

    with pytest.raises(RestrictedOperationError):
        getattr(bank, operation_name)(account.account_number)

    assert account.status is original_status
    assert client.suspicious_activity is True


def test_account_operations_are_allowed_from_five_oclock() -> None:
    bank = make_bank(5, 0)
    client = bank.add_client(make_client())

    account = bank.open_account(client.client_id)

    assert account.status is AccountStatus.ACTIVE
    assert client.suspicious_activity is False


def test_search_accounts_matches_number_and_client_name_case_insensitively() -> None:
    bank = make_bank()
    alice = bank.add_client(make_client())
    bob = bank.add_client(make_client("client-2", "Bob Jones"))
    second_alice_account = bank.open_account(alice.client_id, account_id="ALICE-200")
    first_alice_account = bank.open_account(alice.client_id, account_id="alice-100")
    bob_account = bank.open_account(bob.client_id, account_id="bob-100")
    bank.freeze_account(first_alice_account.account_number)
    bank.close_account(second_alice_account.account_number)

    assert bank.search_accounts(" alice ") == [first_alice_account, second_alice_account]
    assert bank.search_accounts("BOB-100") == [bob_account]
    assert bank.search_accounts("missing") == []
    assert bank.search_accounts("   ") == []


def test_search_results_are_returned_as_a_new_list() -> None:
    bank = make_bank()
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id, account_id="account-1")

    results = bank.search_accounts("account")
    results.clear()

    assert bank.search_accounts("account") == [account]


def test_total_balance_includes_all_registered_account_states() -> None:
    bank = make_bank()
    alice = bank.add_client(make_client())
    bob = bank.add_client(make_client("client-2", "Bob Jones"))
    active = bank.open_account(alice.client_id, balance=Decimal("100.25"))
    frozen = bank.open_account(bob.client_id, balance=50, currency=Currency.USD)
    closed = bank.open_account(bob.client_id, balance=25)
    bank.freeze_account(frozen.account_number)
    bank.close_account(closed.account_number)

    assert bank.get_total_balance() == Decimal("175.25")
    assert active.balance == Decimal("100.25")
    assert frozen.balance == Decimal("50")
    assert closed.balance == Decimal("25")


def test_empty_bank_has_zero_total_and_empty_ranking() -> None:
    bank = make_bank()

    assert bank.get_total_balance() == Decimal("0")
    assert bank.get_clients_ranking() == []


def test_clients_ranking_uses_current_balances_and_deterministic_ties() -> None:
    bank = make_bank()
    alice = bank.add_client(make_client("client-a", "Alice Smith"))
    bob = bank.add_client(make_client("client-b", "Bob Jones"))
    carol = bank.add_client(make_client("client-c", "Carol White"))
    alice_account = bank.open_account(alice.client_id, balance=100)
    bank.open_account(alice.client_id, balance=50)
    bank.open_account(bob.client_id, balance=150)

    alice_account.deposit(25)

    assert bank.get_clients_ranking() == [
        (alice, Decimal("175")),
        (bob, Decimal("150")),
        (carol, Decimal("0")),
    ]


def test_read_only_bank_operations_remain_available_during_restricted_hours() -> None:
    current_time = [datetime(2026, 7, 15, 12, 0)]
    bank = Bank(clock=lambda: current_time[0])
    client = bank.add_client(make_client())
    account = bank.open_account(client.client_id, balance=100)
    current_time[0] = datetime(2026, 7, 16, 1, 0)

    assert bank.authenticate_client(client.client_id, "correct-password") is True
    assert bank.search_accounts(account.account_number) == [account]
    assert bank.get_total_balance() == Decimal("100")
    assert bank.get_clients_ranking() == [(client, Decimal("100"))]
    assert client.suspicious_activity is False
