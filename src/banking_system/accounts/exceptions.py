"""Account operation errors."""


class InvalidOperationError(ValueError):
    """Raised when an account operation has invalid input."""


class AccountFrozenError(InvalidOperationError):
    """Raised when an operation is attempted on a frozen account."""


class AccountClosedError(InvalidOperationError):
    """Raised when an operation is attempted on a closed account."""


class InsufficientFundsError(InvalidOperationError):
    """Raised when an account cannot cover a withdrawal."""
