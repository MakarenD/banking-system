"""Bank orchestration errors."""


class BankError(Exception):
    """Base class for bank orchestration failures."""


class DuplicateClientError(BankError):
    """Raised when a client identifier is already registered."""


class ClientNotFoundError(BankError):
    """Raised when a client cannot be found."""


class ClientBlockedError(BankError):
    """Raised when a blocked client requests an account operation."""


class DuplicateAccountError(BankError):
    """Raised when an account number is already registered."""


class AccountNotFoundError(BankError):
    """Raised when an account cannot be found."""


class RestrictedOperationError(BankError):
    """Raised when an account operation is requested during restricted hours."""
