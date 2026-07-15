"""Transaction operation errors."""


class TransactionError(ValueError):
    """Base error for transaction operations."""


class TransactionStateError(TransactionError):
    """Raised when an operation is unavailable in the current state."""


class DuplicateTransactionError(TransactionError):
    """Raised when a queue already contains a transaction identifier."""


class TransactionNotFoundError(TransactionError):
    """Raised when a transaction is not present in a queue."""


class ExchangeRateNotFoundError(TransactionError):
    """Raised when a required currency conversion rate is unavailable."""
