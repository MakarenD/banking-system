"""Deterministic end-to-end demonstration of the banking system."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import count as counter
from pathlib import Path
from typing import TextIO

from banking_system.accounts import BankAccount, Currency
from banking_system.audit import AuditLevel, AuditLog, AuditRecord, RiskAnalyzer
from banking_system.bank import Bank
from banking_system.clients import Client
from banking_system.reports import AuditReporter, ErrorStatistics, Report, ReportBuilder
from banking_system.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
)

_DEMO_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
_CLIENT_NAMES = (
    "Alice Carter",
    "Bob Evans",
    "Carol Foster",
    "David Green",
    "Emma Harris",
    "Frank Irving",
)
_EVENT_TYPES = frozenset(
    {
        "transaction_queued",
        "transaction_completed",
        "transaction_error",
    }
)


@dataclass(frozen=True, slots=True)
class TransactionStatistics:
    """Summary of transaction outcomes produced by the demonstration."""

    total: int
    queued: int
    completed: int
    rejected: int
    suspicious: int
    remaining_in_queue: int
    errors: ErrorStatistics


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Objects and reports produced by one demonstration run."""

    bank: Bank
    clients: tuple[Client, ...]
    accounts: tuple[BankAccount, ...]
    transactions: tuple[Transaction, ...]
    audit_log: AuditLog
    risk_analyzer: RiskAnalyzer
    event_log: tuple[AuditRecord, ...]
    selected_client: Client
    selected_accounts: tuple[BankAccount, ...]
    selected_history: tuple[Transaction, ...]
    suspicious_operations: tuple[AuditRecord, ...]
    selected_suspicious_operations: tuple[AuditRecord, ...]
    top_clients: tuple[tuple[Client, Decimal], ...]
    statistics: TransactionStatistics
    total_balance: Decimal


@dataclass(frozen=True, slots=True)
class ReportingDemoResult:
    """Reports and files produced by the reporting demonstration."""

    demo: DemoResult
    reports: tuple[Report, ...]
    files: tuple[Path, ...]


def run_demo(*, stream: TextIO | None = None) -> DemoResult:
    """Run the deterministic simulation, render it, and return its complete result."""

    bank, clients, accounts = _initialize_bank()
    transactions = _create_transactions(accounts)
    audit_log = AuditLog(clock=lambda: _DEMO_TIME)
    queue = TransactionQueue(clock=lambda: _DEMO_TIME)
    risk_analyzer = RiskAnalyzer(
        large_amount_threshold=100_000,
        frequent_operations_threshold=11,
    )
    processor = TransactionProcessor(
        clock=_incrementing_clock(),
        audit_log=audit_log,
        risk_analyzer=risk_analyzer,
        max_retries=0,
    )

    for transaction in transactions:
        queue.add(transaction)
        audit_log.record(
            AuditLevel.INFO,
            "transaction_queued",
            "Transaction queued",
            transaction_id=transaction.transaction_id,
            account_number=transaction.sender.account_number,
            details={"queue_size": len(queue)},
            timestamp=_DEMO_TIME,
        )

    processed_transactions = tuple(processor.process_queue(queue, now=_DEMO_TIME))
    reporter = AuditReporter(audit_log)
    suspicious_operations = reporter.suspicious_operations()
    error_statistics = reporter.error_statistics()
    selected_client = clients[0]
    selected_account_numbers = set(selected_client.account_numbers)
    selected_accounts = tuple(bank.search_accounts(selected_client.full_name))
    selected_history = tuple(
        transaction
        for transaction in processed_transactions
        if transaction.sender.account_number in selected_account_numbers
        or transaction.recipient.account_number in selected_account_numbers
    )
    selected_suspicious_operations = tuple(
        record
        for record in suspicious_operations
        if record.account_number in selected_account_numbers
    )
    event_log = tuple(record for record in audit_log.records if record.event_type in _EVENT_TYPES)
    statistics = TransactionStatistics(
        total=len(processed_transactions),
        queued=len(audit_log.filter(event_type="transaction_queued")),
        completed=sum(
            transaction.status is TransactionStatus.COMPLETED
            for transaction in processed_transactions
        ),
        rejected=sum(
            transaction.status is TransactionStatus.FAILED for transaction in processed_transactions
        ),
        suspicious=len(suspicious_operations),
        remaining_in_queue=len(queue),
        errors=error_statistics,
    )
    result = DemoResult(
        bank=bank,
        clients=clients,
        accounts=accounts,
        transactions=processed_transactions,
        audit_log=audit_log,
        risk_analyzer=risk_analyzer,
        event_log=event_log,
        selected_client=selected_client,
        selected_accounts=selected_accounts,
        selected_history=selected_history,
        suspicious_operations=suspicious_operations,
        selected_suspicious_operations=selected_suspicious_operations,
        top_clients=tuple(bank.get_clients_ranking()[:3]),
        statistics=statistics,
        total_balance=bank.get_total_balance(),
    )
    _render_result(result, stream if stream is not None else sys.stdout)
    return result


def run_reporting_demo(
    destination: str | Path = Path("reports/demo"),
    *,
    stream: TextIO | None = None,
) -> ReportingDemoResult:
    """Run the simulation and export deterministic reports and charts."""

    output = stream if stream is not None else sys.stdout
    demo = run_demo(stream=output)
    builder = ReportBuilder(
        demo.bank,
        demo.transactions,
        audit_log=demo.audit_log,
        risk_analyzer=demo.risk_analyzer,
        clock=lambda: _DEMO_TIME,
    )
    reports = (
        builder.build_client_report(demo.selected_client.client_id),
        builder.build_bank_report(),
        builder.build_risk_report(),
    )
    output.write("\nReporting demonstration\n")
    output.write(builder.render_text(reports[0]))

    files: list[Path] = []
    for report in reports:
        files.append(builder.export_to_json(report, destination, overwrite=True))
        files.append(builder.export_to_csv(report, destination, overwrite=True))
    files.extend(
        builder.save_charts(
            destination,
            client_id=demo.selected_client.client_id,
            overwrite=True,
        )
    )
    output.write("Created files\n")
    for path in files:
        output.write(f"- {path.resolve()}\n")
    return ReportingDemoResult(demo=demo, reports=reports, files=tuple(files))


def main() -> None:
    """Run the complete demonstration and export reporting artifacts."""

    run_reporting_demo()


def _incrementing_clock() -> Callable[[], datetime]:
    ticks = counter()
    return lambda: _DEMO_TIME + timedelta(microseconds=next(ticks))


def _initialize_bank() -> tuple[Bank, tuple[Client, ...], tuple[BankAccount, ...]]:
    bank = Bank("Example Bank", clock=lambda: _DEMO_TIME)
    clients = tuple(
        bank.add_client(
            Client(
                full_name,
                30 + index,
                {"email": f"client-{index:03d}@example.com"},
                "demo-password",
                client_id=f"client-{index:03d}",
            )
        )
        for index, full_name in enumerate(_CLIENT_NAMES, start=1)
    )
    accounts = tuple(
        bank.open_account(
            client.client_id,
            account_id=f"ACC-{account_index:03d}",
            balance=10_000,
            currency=Currency.RUB,
        )
        for account_index, client in enumerate(
            (client for client in clients for _ in range(2)),
            start=1,
        )
    )
    return bank, clients, accounts


def _create_transactions(accounts: tuple[BankAccount, ...]) -> tuple[Transaction, ...]:
    transaction_specs: list[tuple[BankAccount, BankAccount, int]] = []
    account_pairs = (
        (accounts[0], accounts[5], accounts[7]),
        (accounts[2], accounts[7], accounts[9]),
        (accounts[4], accounts[9], accounts[11]),
        (accounts[6], accounts[11], accounts[3]),
    )
    for sender, known_recipient, new_recipient in account_pairs:
        transaction_specs.extend((sender, known_recipient, 250) for _ in range(8))
        transaction_specs.append((sender, known_recipient, 50_000))
        transaction_specs.append((sender, new_recipient, 100_000))

    return tuple(
        Transaction(
            TransactionType.INTERNAL_TRANSFER,
            amount,
            Currency.RUB,
            sender,
            recipient,
            transaction_id=f"TX-{index:03d}",
            created_at=_DEMO_TIME,
        )
        for index, (sender, recipient, amount) in enumerate(transaction_specs, start=1)
    )


def _render_result(result: DemoResult, stream: TextIO) -> None:
    stream.write("Banking System demonstration\n")
    stream.write(
        f"Initialized: {len(result.clients)} clients, {len(result.accounts)} accounts, "
        f"{len(result.transactions)} transactions\n\n"
    )
    stream.write("Transaction log\n")
    labels = {
        "transaction_queued": "queued",
        "transaction_completed": "completed",
        "transaction_error": "rejected",
    }
    for record in result.event_log:
        stream.write(f"[{labels[record.event_type]}] {record.transaction_id}: {record.message}\n")

    stream.write(f"\nClient scenario: {result.selected_client.full_name}\n")
    stream.write("Accounts\n")
    for account in result.selected_accounts:
        stream.write(f"- {account.account_number}: {account.balance} {account.currency.value}\n")
    stream.write("Transaction history\n")
    for transaction in result.selected_history:
        stream.write(
            f"- {transaction.transaction_id}: {transaction.amount} "
            f"{transaction.currency.value}, {transaction.status.value}\n"
        )
    stream.write("Suspicious operations\n")
    for record in result.selected_suspicious_operations:
        stream.write(
            f"- {record.transaction_id}: {record.details['risk_level']} "
            f"({', '.join(record.details['risk_factors'])})\n"
        )

    stream.write("\nTop 3 clients\n")
    for position, (client, balance) in enumerate(result.top_clients, start=1):
        stream.write(f"{position}. {client.full_name}: {balance} nominal units\n")
    stream.write("Transaction statistics\n")
    stream.write(f"- total: {result.statistics.total}\n")
    stream.write(f"- queued: {result.statistics.queued}\n")
    stream.write(f"- completed: {result.statistics.completed}\n")
    stream.write(f"- rejected: {result.statistics.rejected}\n")
    stream.write(f"- suspicious: {result.statistics.suspicious}\n")
    stream.write(f"- remaining in queue: {result.statistics.remaining_in_queue}\n")
    stream.write(f"- processing errors: {result.statistics.errors.total_errors}\n")
    for error_type, count in sorted(result.statistics.errors.errors_by_type.items()):
        stream.write(f"  - {error_type}: {count}\n")
    stream.write(f"Total balance: {result.total_balance} nominal units\n")


if __name__ == "__main__":
    main()
