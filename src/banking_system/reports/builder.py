"""Report aggregation, serialization, export, and visualization."""

import csv
import io
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from matplotlib import pyplot as plt
from matplotlib.figure import Figure

from banking_system.accounts import BankAccount
from banking_system.audit import AuditLog, RiskAnalyzer, RiskAssessment, RiskFactor, RiskLevel
from banking_system.bank import Bank
from banking_system.clients import Client
from banking_system.transactions import Transaction, TransactionStatus

from .audit import AuditReporter
from .enums import ReportType
from .models import ClientRiskProfile, Report

_JSON_INDENT = 2


class ReportBuilder:
    """Build reports and charts from existing banking domain objects."""

    def __init__(
        self,
        bank: Bank,
        transactions: Iterable[Transaction] = (),
        *,
        audit_log: AuditLog | None = None,
        risk_analyzer: RiskAnalyzer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(bank, Bank):
            raise TypeError("Report builder requires a Bank instance")
        try:
            transaction_snapshot = tuple(transactions)
        except TypeError as error:
            raise TypeError("Transactions must be an iterable of Transaction instances") from error
        if not all(isinstance(item, Transaction) for item in transaction_snapshot):
            raise TypeError("Transactions must contain only Transaction instances")
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("Audit log must be an AuditLog instance")
        if risk_analyzer is not None and not isinstance(risk_analyzer, RiskAnalyzer):
            raise TypeError("Risk analyzer must be a RiskAnalyzer instance")
        if clock is not None and not callable(clock):
            raise TypeError("Report clock must be callable")

        registered_account_ids = {id(account) for account in bank.accounts}
        if any(
            id(transaction.sender) not in registered_account_ids
            and id(transaction.recipient) not in registered_account_ids
            for transaction in transaction_snapshot
        ):
            raise ValueError("Every transaction must involve an account registered with the bank")

        self._bank = bank
        self._transactions = transaction_snapshot
        self._audit_log = audit_log or AuditLog()
        self._risk_analyzer = risk_analyzer or RiskAnalyzer()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._audit_reporter = AuditReporter(self._audit_log)

    def build_report(
        self,
        report_type: ReportType | str,
        *,
        client_id: str | None = None,
    ) -> Report:
        """Build a selected report category and validate its required arguments."""

        try:
            normalized_type = (
                report_type
                if isinstance(report_type, ReportType)
                else ReportType(str(report_type).strip().lower())
            )
        except (TypeError, ValueError) as error:
            allowed = ", ".join(item.value for item in ReportType)
            raise ValueError(f"Report type must be one of: {allowed}") from error
        if normalized_type is ReportType.CLIENT:
            if client_id is None:
                raise ValueError("Client identifier is required for a client report")
            return self.build_client_report(client_id)
        if client_id is not None:
            raise ValueError("Client identifier is supported only for a client report")
        if normalized_type is ReportType.BANK:
            return self.build_bank_report()
        return self.build_risk_report()

    def build_client_report(self, client_id: str) -> Report:
        """Build account, transaction, and risk details for one client."""

        client = self._bank.get_client(client_id)
        accounts = self._bank.get_client_accounts(client.client_id)
        account_ids = {id(account) for account in accounts}
        account_numbers = {account.account_number for account in accounts}
        transactions = tuple(
            transaction
            for transaction in self._transactions
            if id(transaction.sender) in account_ids or id(transaction.recipient) in account_ids
        )
        risk_profile = self._audit_reporter.client_risk_profile(client)
        suspicious = tuple(
            assessment
            for assessment in self._risk_analyzer.assessments
            if assessment.account_number in account_numbers
            and assessment.level in {RiskLevel.MEDIUM, RiskLevel.HIGH}
        )

        data = {
            "client": self._client_data(client),
            "accounts": [account.get_account_info() for account in accounts],
            "balances_by_currency": self._balances_by_currency(accounts),
            "transactions": self._transaction_summary(transactions),
            "suspicious_operations": [
                self._assessment_data(assessment) for assessment in suspicious
            ],
            "risk_profile": self._risk_profile_data(risk_profile),
        }
        return self._report(ReportType.CLIENT, f"Client report: {client.full_name}", data)

    def build_bank_report(self) -> Report:
        """Build bank-wide account, transaction, balance, and risk aggregates."""

        accounts = self._bank.accounts
        account_types = Counter(type(account).__name__ for account in accounts)
        currencies = Counter(account.currency.value for account in accounts)
        completed = tuple(
            transaction
            for transaction in self._transactions
            if transaction.status is TransactionStatus.COMPLETED
        )
        successful_amounts = self._amounts_by_currency(completed)
        risk_levels = Counter(
            assessment.level.value for assessment in self._risk_analyzer.assessments
        )

        data = {
            "bank": {"name": self._bank.name},
            "clients_count": len(self._bank.clients),
            "accounts_count": len(accounts),
            "accounts_by_type": dict(sorted(account_types.items())),
            "accounts_by_currency": dict(sorted(currencies.items())),
            # Currency buckets avoid implying that nominal values are convertible.
            "balances_by_currency": self._balances_by_currency(accounts),
            "transactions": self._transaction_summary(self._transactions),
            "successful_amounts_by_currency": successful_amounts,
            "risk_levels": self._complete_risk_counts(risk_levels),
            "errors": self._error_data(),
            "client_ranking_by_currency": self._client_ranking_by_currency(accounts),
        }
        return self._report(ReportType.BANK, f"Bank report: {self._bank.name}", data)

    def build_risk_report(self) -> Report:
        """Build risk statistics from existing analyzer and audit results."""

        assessments = self._risk_analyzer.assessments
        level_counts = Counter(assessment.level.value for assessment in assessments)
        factor_counts = Counter(
            factor.value for assessment in assessments for factor in assessment.factors
        )
        suspicious = tuple(
            assessment
            for assessment in assessments
            if assessment.level in {RiskLevel.MEDIUM, RiskLevel.HIGH}
        )
        blocked_records = tuple(
            record
            for record in self._audit_log.filter(event_type="transaction_error")
            if record.details.get("error_type") == "RiskBlockedError"
        )
        profiles = [
            self._risk_profile_data(self._audit_reporter.client_risk_profile(client))
            for client in self._bank.clients
        ]

        data = {
            "analyzed_operations": len(assessments),
            "operations_by_level": self._complete_risk_counts(level_counts),
            "suspicious_operations": [
                self._assessment_data(assessment) for assessment in suspicious
            ],
            "blocked_operations": [record.to_dict() for record in blocked_records],
            "risk_factors": {factor.value: factor_counts[factor.value] for factor in RiskFactor},
            "errors": self._error_data(),
            "client_profiles": profiles,
        }
        return self._report(ReportType.RISK, f"Risk report: {self._bank.name}", data)

    def render_text(self, report: Report) -> str:
        """Render a report as readable plain text."""

        report = self._validate_report(report)
        lines = [report.title, f"Generated at: {report.generated_at.isoformat()}"]
        self._append_text(lines, report.data)
        return "\n".join(lines) + "\n"

    def to_json(self, report: Report) -> str:
        """Serialize a report as indented UTF-8-safe JSON text."""

        report = self._validate_report(report)
        return json.dumps(
            self._json_compatible(report.to_dict()),
            ensure_ascii=False,
            indent=_JSON_INDENT,
            allow_nan=False,
        )

    def to_csv(self, report: Report) -> str:
        """Serialize a report as stable field/value CSV rows."""

        report = self._validate_report(report)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(("field", "value"))
        for field, value in self._flatten(report.to_dict()):
            writer.writerow((field, self._scalar_text(value)))
        return stream.getvalue()

    def export_to_json(
        self,
        report: Report,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Save a report as JSON and return the created path."""

        report = self._validate_report(report)
        path = self._resolve_export_path(destination, report, ".json")
        self._prepare_output(path, overwrite=overwrite)
        path.write_text(self.to_json(report) + "\n", encoding="utf-8")
        return path

    def export_to_csv(
        self,
        report: Report,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Save a report as CSV and return the created path."""

        report = self._validate_report(report)
        path = self._resolve_export_path(destination, report, ".csv")
        self._prepare_output(path, overwrite=overwrite)
        # newline="" is required by csv to avoid platform-specific blank rows.
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            csv_file.write(self.to_csv(report))
        return path

    def build_transaction_status_chart(self) -> Figure:
        """Create a pie chart of transaction outcomes."""

        figure, axis = plt.subplots(figsize=(7, 5))
        counts = Counter(transaction.status.value for transaction in self._transactions)
        populated = [
            (status.value, counts[status.value])
            for status in TransactionStatus
            if counts[status.value]
        ]
        if populated:
            labels, values = zip(*populated, strict=True)
            axis.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
        else:
            self._empty_axis(axis, "No transaction data")
        axis.set_title("Transactions by status")
        figure.tight_layout()
        return figure

    def build_client_activity_chart(self) -> Figure:
        """Create a bar chart of transactions involving each client."""

        figure, axis = plt.subplots(figsize=(9, 5))
        counts = self._client_transaction_counts()
        if counts:
            labels = [client.full_name for client in self._bank.clients]
            values = [counts[client.client_id] for client in self._bank.clients]
            axis.bar(labels, values)
            axis.tick_params(axis="x", rotation=30)
            axis.set_ylabel("Transactions")
        else:
            self._empty_axis(axis, "No client transaction data")
        axis.set_title("Transactions by client")
        figure.tight_layout()
        return figure

    def build_balance_history_chart(self, client_id: str | None = None) -> Figure:
        """Create currency-separated balance histories reconstructed from settlements."""

        accounts = (
            self._bank.accounts
            if client_id is None
            else self._bank.get_client_accounts(self._bank.get_client(client_id).client_id)
        )
        histories = self._balance_histories(accounts)
        currencies = sorted({account.currency.value for account in accounts})
        if not currencies:
            currencies = ["balance"]
        figure, axes = plt.subplots(
            len(currencies),
            1,
            figsize=(10, max(4, 3 * len(currencies))),
            squeeze=False,
        )
        for currency, axis in zip(currencies, axes.flat, strict=True):
            plotted = False
            for account in accounts:
                if account.currency.value != currency or account.account_number not in histories:
                    continue
                timestamps, balances = histories[account.account_number]
                axis.plot(
                    timestamps,
                    balances,
                    marker="o",
                    drawstyle="steps-post",
                    label=account.account_number,
                )
                plotted = True
            if plotted:
                axis.set_ylabel(f"Balance ({currency})")
                axis.legend()
                axis.grid(alpha=0.3)
            else:
                self._empty_axis(axis, "No completed transaction history")
            axis.set_xlabel("Processed at")
            axis.set_title(
                f"Balance history — {currency}" if currency != "balance" else "Balance history"
            )
        figure.autofmt_xdate()
        figure.tight_layout()
        return figure

    def save_charts(
        self,
        destination: str | Path,
        *,
        client_id: str | None = None,
        overwrite: bool = False,
    ) -> tuple[Path, ...]:
        """Save all PNG charts, close their figures, and return their paths."""

        if client_id is not None:
            # Validate before writing any chart so a bad client cannot leave partial output.
            self._bank.get_client(client_id)
        directory = self._validate_directory(destination)
        directory.mkdir(parents=True, exist_ok=True)
        chart_builders = (
            ("transaction_statuses.png", self.build_transaction_status_chart),
            ("client_activity.png", self.build_client_activity_chart),
            ("balance_history.png", lambda: self.build_balance_history_chart(client_id)),
        )
        paths = tuple(directory / name for name, _ in chart_builders)
        for path in paths:
            self._prepare_output(path, overwrite=overwrite)

        created: list[Path] = []
        for path, (_, build_chart) in zip(paths, chart_builders, strict=True):
            figure = build_chart()
            try:
                figure.savefig(path, format="png", dpi=150, bbox_inches="tight")
                created.append(path)
            finally:
                # Closing even after save errors prevents long-running notebooks from leaking figures.
                plt.close(figure)
        return tuple(created)

    def _report(self, report_type: ReportType, title: str, data: Mapping[str, Any]) -> Report:
        timestamp = self._clock()
        if not isinstance(timestamp, datetime):
            raise TypeError("Report clock must return a datetime")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        return Report(report_type, title, timestamp, data)

    @staticmethod
    def _client_data(client: Client) -> dict[str, Any]:
        return {
            "client_id": client.client_id,
            "full_name": client.full_name,
            "status": client.status,
            "suspicious_activity": client.suspicious_activity,
        }

    @staticmethod
    def _balances_by_currency(accounts: Iterable[BankAccount]) -> dict[str, Decimal]:
        totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for account in accounts:
            totals[account.currency.value] += account.balance
        return dict(sorted(totals.items()))

    @staticmethod
    def _amounts_by_currency(transactions: Iterable[Transaction]) -> dict[str, Decimal]:
        totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for transaction in transactions:
            totals[transaction.currency.value] += transaction.amount
        return dict(sorted(totals.items()))

    @staticmethod
    def _transaction_summary(transactions: Iterable[Transaction]) -> dict[str, Any]:
        items = tuple(transactions)
        counts = Counter(transaction.status.value for transaction in items)
        return {
            "total": len(items),
            "completed": counts[TransactionStatus.COMPLETED.value],
            "rejected": counts[TransactionStatus.FAILED.value],
            "by_status": {status.value: counts[status.value] for status in TransactionStatus},
            "items": [transaction.get_transaction_info() for transaction in items],
        }

    @staticmethod
    def _assessment_data(assessment: RiskAssessment) -> dict[str, Any]:
        return {
            "transaction_id": assessment.transaction_id,
            "account_number": assessment.account_number,
            "recipient_account_number": assessment.recipient_account_number,
            "timestamp": assessment.timestamp,
            "risk_level": assessment.level,
            "risk_factors": list(assessment.factors),
            "score": assessment.score,
        }

    @staticmethod
    def _risk_profile_data(profile: ClientRiskProfile) -> dict[str, Any]:
        return {
            "client_id": profile.client_id,
            "account_numbers": list(profile.account_numbers),
            "total_operations": profile.total_operations,
            "operations_by_level": {
                level.value: profile.operations_by_level[level] for level in RiskLevel
            },
            "highest_risk_level": profile.highest_risk_level,
            "factor_counts": dict(sorted(profile.factor_counts.items())),
        }

    @staticmethod
    def _complete_risk_counts(counts: Mapping[str, int]) -> dict[str, int]:
        return {level.value: counts.get(level.value, 0) for level in RiskLevel}

    def _error_data(self) -> dict[str, Any]:
        statistics = self._audit_reporter.error_statistics()
        return {
            "total": statistics.total_errors,
            "by_type": dict(sorted(statistics.errors_by_type.items())),
        }

    def _client_ranking_by_currency(
        self, accounts: Iterable[BankAccount]
    ) -> dict[str, list[dict[str, Any]]]:
        balances: defaultdict[str, defaultdict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal("0"))
        )
        for account in accounts:
            owner = self._bank.get_account_owner(account.account_number)
            balances[account.currency.value][owner.client_id] += account.balance

        rankings: dict[str, list[dict[str, Any]]] = {}
        for currency, client_balances in sorted(balances.items()):
            ordered = sorted(client_balances.items(), key=lambda item: (-item[1], item[0]))
            rankings[currency] = [
                {
                    "position": position,
                    "client_id": client_id,
                    "full_name": self._bank.get_client(client_id).full_name,
                    "balance": balance,
                    "currency": currency,
                }
                for position, (client_id, balance) in enumerate(ordered, start=1)
            ]
        return rankings

    def _client_transaction_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        registered_accounts = {
            id(account): self._bank.get_account_owner(account.account_number).client_id
            for account in self._bank.accounts
        }
        for transaction in self._transactions:
            involved = {
                registered_accounts.get(id(transaction.sender)),
                registered_accounts.get(id(transaction.recipient)),
            }
            for client_id in involved - {None}:
                counts[client_id] += 1
        return counts

    def _balance_histories(
        self, accounts: Iterable[BankAccount]
    ) -> dict[str, tuple[list[datetime], list[Decimal]]]:
        account_map = {id(account): account for account in accounts}
        events: defaultdict[int, list[tuple[datetime, Decimal]]] = defaultdict(list)
        for transaction in self._transactions:
            if (
                transaction.status is not TransactionStatus.COMPLETED
                or transaction.processed_at is None
            ):
                continue
            if id(transaction.sender) in account_map:
                events[id(transaction.sender)].append(
                    (transaction.processed_at, -(transaction.amount + transaction.commission))
                )
            if id(transaction.recipient) in account_map and transaction.received_amount is not None:
                events[id(transaction.recipient)].append(
                    (transaction.processed_at, transaction.received_amount)
                )

        histories: dict[str, tuple[list[datetime], list[Decimal]]] = {}
        for account_id, account_events in events.items():
            account_events.sort(key=lambda item: item[0])
            # Final balances are authoritative; reversing exact successful deltas avoids
            # inventing an initial snapshot that the domain model never stored.
            account = account_map[account_id]
            running = account.balance - sum((delta for _, delta in account_events), Decimal("0"))
            timestamps = [account_events[0][0]]
            balances = [running]
            for timestamp, delta in account_events:
                running += delta
                timestamps.append(timestamp)
                balances.append(running)
            histories[account.account_number] = (timestamps, balances)
        return histories

    @classmethod
    def _json_compatible(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value) and not isinstance(value, type):
            return cls._json_compatible(asdict(value))
        if isinstance(value, Mapping):
            return {
                cls._scalar_text(key): cls._json_compatible(item) for key, item in value.items()
            }
        if isinstance(value, (set, frozenset)):
            return sorted(
                (cls._json_compatible(item) for item in value),
                key=cls._scalar_text,
            )
        if isinstance(value, (list, tuple)):
            return [cls._json_compatible(item) for item in value]
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise TypeError(f"Unsupported report value: {type(value).__name__}")

    @classmethod
    def _flatten(cls, value: Any, prefix: str = "") -> list[tuple[str, Any]]:
        compatible = cls._json_compatible(value)
        rows: list[tuple[str, Any]] = []
        if isinstance(compatible, Mapping):
            for key, item in compatible.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                rows.extend(cls._flatten(item, child))
        elif isinstance(compatible, list):
            if compatible:
                for index, item in enumerate(compatible):
                    rows.extend(cls._flatten(item, f"{prefix}[{index}]"))
            else:
                rows.append((prefix, "[]"))
        else:
            rows.append((prefix, compatible))
        return rows

    @classmethod
    def _append_text(cls, lines: list[str], value: Any, *, indent: int = 0) -> None:
        compatible = cls._json_compatible(value)
        padding = "  " * indent
        if isinstance(compatible, Mapping):
            for key, item in compatible.items():
                label = str(key).replace("_", " ").capitalize()
                if isinstance(item, (Mapping, list)):
                    lines.append(f"{padding}{label}:")
                    cls._append_text(lines, item, indent=indent + 1)
                else:
                    lines.append(f"{padding}{label}: {cls._scalar_text(item)}")
        elif isinstance(compatible, list):
            if not compatible:
                lines.append(f"{padding}(none)")
            for item in compatible:
                if isinstance(item, (Mapping, list)):
                    lines.append(f"{padding}-")
                    cls._append_text(lines, item, indent=indent + 1)
                else:
                    lines.append(f"{padding}- {cls._scalar_text(item)}")

    @staticmethod
    def _scalar_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, Enum):
            return str(value.value)
        return str(value)

    @staticmethod
    def _validate_report(report: Report) -> Report:
        if not isinstance(report, Report):
            raise TypeError("Expected a Report instance")
        return report

    @staticmethod
    def _validate_directory(destination: str | Path) -> Path:
        if not isinstance(destination, (str, Path)):
            raise TypeError("Destination must be a string or Path")
        path = Path(destination)
        if path.exists() and not path.is_dir():
            raise NotADirectoryError(f"Chart destination is not a directory: {path}")
        return path

    @staticmethod
    def _resolve_export_path(destination: str | Path, report: Report, suffix: str) -> Path:
        if not isinstance(destination, (str, Path)):
            raise TypeError("Destination must be a string or Path")
        path = Path(destination)
        if path.exists() and path.is_dir():
            return path / f"{report.report_type.value}_report{suffix}"
        if path.suffix == "":
            if path.exists():
                raise NotADirectoryError(f"Export destination is not a directory: {path}")
            return path / f"{report.report_type.value}_report{suffix}"
        if path.suffix.lower() != suffix:
            raise ValueError(f"Destination must have a {suffix} suffix")
        return path

    @staticmethod
    def _prepare_output(path: Path, *, overwrite: bool) -> None:
        if path.exists() and path.is_dir():
            raise IsADirectoryError(f"Output path is a directory: {path}")
        if path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _empty_axis(axis: Any, message: str) -> None:
        axis.text(0.5, 0.5, message, ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
        axis.set_yticks([])
