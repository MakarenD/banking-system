"""Values used by account models."""

from enum import StrEnum


class AccountStatus(StrEnum):
    """Operational state of an account."""

    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class Currency(StrEnum):
    """Currencies supported by bank accounts."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"
