"""Audit and risk analysis errors."""


class RiskBlockedError(ValueError):
    """Raised internally when risk controls block a transaction."""
