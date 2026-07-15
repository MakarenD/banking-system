import pytest

from banking_system.clients import Client, ClientStatus


def make_client(**overrides: object) -> Client:
    values: dict[str, object] = {
        "full_name": "Alice Smith",
        "age": 30,
        "contacts": {"email": "alice@example.com"},
        "password": "correct-password",
        "client_id": "client-1",
    }
    values.update(overrides)
    return Client(**values)  # type: ignore[arg-type]


def test_client_normalizes_public_state_and_starts_without_accounts() -> None:
    client = Client(
        "  Alice Smith  ",
        18,
        {" email ": " alice@example.com "},
        "correct-password",
        client_id=" client-1 ",
        status=" ACTIVE ",
    )

    assert client.full_name == "Alice Smith"
    assert client.age == 18
    assert client.client_id == "client-1"
    assert client.status is ClientStatus.ACTIVE
    assert client.contacts == {"email": "alice@example.com"}
    assert client.account_numbers == []
    assert client.failed_authentication_attempts == 0
    assert client.suspicious_activity is False


def test_client_generates_unique_short_uuid_identifiers() -> None:
    first_client = make_client(client_id=None)
    second_client = make_client(client_id=None)

    assert len(first_client.client_id) == 8
    assert all(character in "0123456789abcdef" for character in first_client.client_id)
    assert first_client.client_id != second_client.client_id


@pytest.mark.parametrize("age", [0, 17, -1])
def test_client_rejects_age_below_eighteen(age: int) -> None:
    with pytest.raises(ValueError, match="at least 18"):
        make_client(age=age)


@pytest.mark.parametrize("age", [18.0, "18", True, None])
def test_client_requires_integer_age(age: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        make_client(age=age)


@pytest.mark.parametrize("full_name", ["", "   "])
def test_client_rejects_empty_full_name(full_name: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        make_client(full_name=full_name)


def test_client_rejects_non_string_full_name() -> None:
    with pytest.raises(TypeError, match="string"):
        make_client(full_name=42)


@pytest.mark.parametrize("client_id", ["", "   "])
def test_client_rejects_empty_identifier(client_id: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        make_client(client_id=client_id)


def test_client_rejects_non_string_identifier() -> None:
    with pytest.raises(TypeError, match="string"):
        make_client(client_id=42)


def test_client_contacts_are_defensive_copies() -> None:
    source_contacts = {"email": "alice@example.com"}
    client = make_client(contacts=source_contacts)

    source_contacts["email"] = "changed@example.com"
    returned_contacts = client.contacts
    returned_contacts["phone"] = "+1-555-0100"

    assert client.contacts == {"email": "alice@example.com"}


@pytest.mark.parametrize(
    "contacts, error_type",
    [
        ({}, ValueError),
        ({"": "alice@example.com"}, ValueError),
        ({"email": "   "}, ValueError),
        ({1: "alice@example.com"}, TypeError),
        ({"email": 123}, TypeError),
        (["alice@example.com"], TypeError),
    ],
)
def test_client_rejects_invalid_contacts(contacts: object, error_type: type[Exception]) -> None:
    with pytest.raises(error_type):
        make_client(contacts=contacts)


def test_client_rejects_duplicate_normalized_contact_names() -> None:
    with pytest.raises(ValueError, match="duplicate name"):
        make_client(
            contacts={
                "email": "alice@example.com",
                " email ": "backup@example.com",
            }
        )


@pytest.mark.parametrize("password", ["", None, 123])
def test_client_rejects_invalid_password(password: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_client(password=password)


def test_client_rejects_unsupported_status() -> None:
    with pytest.raises(ValueError, match="Status must be one of"):
        make_client(status="pending")


def test_client_account_numbers_are_returned_as_a_copy() -> None:
    client = make_client()

    returned_numbers = client.account_numbers
    returned_numbers.append("external-account")

    assert client.account_numbers == []
