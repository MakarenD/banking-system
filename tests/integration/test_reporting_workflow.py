import csv
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from banking_system.accounts import Currency
from banking_system.audit import AuditLog, RiskAnalyzer
from banking_system.bank import Bank
from banking_system.clients import Client
from banking_system.reports import ReportBuilder
from banking_system.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionStatus,
    TransactionType,
)


def test_reporting_workflow_uses_processed_transactions_audit_and_risk(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    bank = Bank("Integration Bank", clock=lambda: now)
    sender_client = bank.add_client(
        Client("Sender", 30, {"email": "sender@example.com"}, "secret", client_id="sender")
    )
    recipient_client = bank.add_client(
        Client(
            "Recipient",
            31,
            {"email": "recipient@example.com"},
            "secret",
            client_id="recipient",
        )
    )
    sender = bank.open_account(
        sender_client.client_id,
        account_id="SENDER-RUB",
        balance=5_000,
        currency=Currency.RUB,
    )
    recipient = bank.open_account(
        recipient_client.client_id,
        account_id="RECIPIENT-USD",
        currency=Currency.USD,
    )
    audit_log = AuditLog(clock=lambda: now)
    risk_analyzer = RiskAnalyzer(large_amount_threshold=1_000)
    ticks = iter(now + timedelta(seconds=index) for index in range(30))
    processor = TransactionProcessor(
        exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")},
        audit_log=audit_log,
        risk_analyzer=risk_analyzer,
        clock=lambda: next(ticks),
    )
    completed = Transaction(
        TransactionType.EXTERNAL_TRANSFER,
        100,
        Currency.RUB,
        sender,
        recipient,
        transaction_id="COMPLETED",
        created_at=now,
    )
    blocked = Transaction(
        TransactionType.EXTERNAL_TRANSFER,
        2_000,
        Currency.RUB,
        sender,
        recipient,
        transaction_id="BLOCKED",
        created_at=now + timedelta(seconds=1),
    )
    processor.process(completed)
    processor.process(blocked)

    builder = ReportBuilder(
        bank,
        (completed, blocked),
        audit_log=processor.audit_log,
        risk_analyzer=processor.risk_analyzer,
        clock=lambda: now,
    )
    reports = (
        builder.build_client_report(sender_client.client_id),
        builder.build_bank_report(),
        builder.build_risk_report(),
    )
    paths = []
    for report in reports:
        paths.append(builder.export_to_json(report, tmp_path))
        paths.append(builder.export_to_csv(report, tmp_path))
    paths.extend(builder.save_charts(tmp_path, client_id=sender_client.client_id))

    assert completed.status is TransactionStatus.COMPLETED
    assert blocked.status is TransactionStatus.FAILED
    assert len(paths) == 9
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
    assert (
        json.loads((tmp_path / "risk_report.json").read_text(encoding="utf-8"))["data"][
            "blocked_operations"
        ][0]["transaction_id"]
        == "BLOCKED"
    )
    csv_rows = list(csv.reader((tmp_path / "client_report.csv").open(encoding="utf-8", newline="")))
    assert ["data.transactions.completed", "1"] in csv_rows
    assert ["data.transactions.rejected", "1"] in csv_rows
