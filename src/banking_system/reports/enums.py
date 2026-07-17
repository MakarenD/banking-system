"""Values used by reporting components."""

from enum import StrEnum


class ReportType(StrEnum):
    """Categories supported by ``ReportBuilder``."""

    CLIENT = "client"
    BANK = "bank"
    RISK = "risk"
