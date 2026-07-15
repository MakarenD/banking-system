"""Values used by client models."""

from enum import StrEnum


class ClientStatus(StrEnum):
    """Access state of a bank client."""

    ACTIVE = "active"
    BLOCKED = "blocked"
