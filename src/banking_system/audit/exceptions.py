"""Audit and risk analysis errors."""


class RiskBlockedError(ValueError):
    """Raised internally when a high-risk transaction is blocked."""
