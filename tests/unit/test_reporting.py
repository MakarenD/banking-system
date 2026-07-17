import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import UUID

import matplotlib.pyplot as plt
import pytest
from matplotlib.figure import Figure

from banking_system.accounts import Currency
from banking_system.audit import AuditLog, RiskAnalyzer, RiskLevel
from banking_system.bank import Bank, ClientNotFoundError
from banking_system.clients import Client, ClientStatus
from banking_system.reports import Report, ReportBuilder, ReportType
from banking_system.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionType,
)

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def make_builder() -> tuple[ReportBuilder, Client, tuple[Transaction, ...]]:
    bank = Bank("Reporting Bank", clock=lambda: NOW)
    alice = bank.add_client(
        Client(
            "Алиса Иванова",
            30,
            {"email": "alice@example.com"},
            "secret",
            client_id="alice",
        )
    )
    bob = bank.add_client(
        Client(
            "Bob Smith",
            31,
            {"email": "bob@example.com"},
            "secret",
            client_id="bob",
        )
    )
    sender = bank.open_account(
        alice.client_id,
        account_id="RUB-1",
        balance=1_000,
        currency=Currency.RUB,
    )
    recipient = bank.open_account(
        bob.client_id,
        account_id="USD-1",
        currency=Currency.USD,
    )
    audit_log = AuditLog(clock=lambda: NOW)
    risk_analyzer = RiskAnalyzer(large_amount_threshold=1_000)
    ticks = iter(NOW + timedelta(seconds=index) for index in range(100))
    processor = TransactionProcessor(
        exchange_rates={(Currency.RUB, Currency.USD): Decimal("0.01")},
        external_fee_rate=Decimal("0.01"),
        audit_log=audit_log,
        risk_analyzer=risk_analyzer,
        clock=lambda: next(ticks),
    )
    transactions = (
        Transaction(
            TransactionType.EXTERNAL_TRANSFER,
            100,
            Currency.RUB,
            sender,
            recipient,
            transaction_id="TX-1",
            created_at=NOW,
        ),
        Transaction(
            TransactionType.EXTERNAL_TRANSFER,
            50,
            Currency.RUB,
            sender,
            recipient,
            transaction_id="TX-2",
            created_at=NOW + timedelta(seconds=1),
        ),
        Transaction(
            TransactionType.EXTERNAL_TRANSFER,
            2_000,
            Currency.RUB,
            sender,
            recipient,
            transaction_id="TX-3",
            created_at=NOW + timedelta(seconds=2),
        ),
        Transaction(
            TransactionType.EXTERNAL_TRANSFER,
            900,
            Currency.RUB,
            sender,
            recipient,
            transaction_id="TX-4",
            created_at=NOW + timedelta(seconds=3),
        ),
    )
    for transaction in transactions:
        processor.process(transaction)
    builder = ReportBuilder(
        bank,
        transactions,
        audit_log=audit_log,
        risk_analyzer=risk_analyzer,
        clock=lambda: NOW,
    )
    return builder, alice, transactions


@pytest.fixture(scope="module")
def reporting_context() -> tuple[ReportBuilder, Client, tuple[Transaction, ...]]:
    return make_builder()


def test_client_text_report_uses_accounts_transactions_and_risk(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, alice, _ = reporting_context

    text = builder.render_text(builder.build_client_report(alice.client_id))

    assert "Client report: Алиса Иванова" in text
    assert "RUB-1" in text
    assert "Completed: 2" in text
    assert "Rejected: 2" in text
    assert "Highest risk level: high" in text


def test_bank_text_report_keeps_currency_totals_separate(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, _, _ = reporting_context

    report = builder.build_bank_report()
    text = builder.render_text(report)

    assert "Bank report: Reporting Bank" in text
    assert report.data["clients_count"] == 2
    assert report.data["accounts_count"] == 2
    assert report.data["balances_by_currency"] == {
        "RUB": Decimal("848.50"),
        "USD": Decimal("1.50"),
    }
    rankings = report.data["client_ranking_by_currency"]
    assert rankings["RUB"][0]["client_id"] == "alice"
    assert rankings["USD"][0]["client_id"] == "bob"
    assert "Client ranking by currency" in text


def test_risk_text_report_uses_existing_assessments_and_errors(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, _, _ = reporting_context

    report = builder.build_risk_report()
    text = builder.render_text(report)

    assert report.data["analyzed_operations"] == 4
    assert report.data["operations_by_level"] == {"low": 2, "medium": 1, "high": 1}
    assert len(report.data["blocked_operations"]) == 1
    assert report.data["errors"]["total"] == 2
    assert "Risk report: Reporting Bank" in text


def test_build_report_dispatches_and_rejects_unsupported_arguments(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, alice, _ = reporting_context

    assert (
        builder.build_report("client", client_id=alice.client_id).report_type is ReportType.CLIENT
    )
    assert builder.build_report(ReportType.BANK).report_type is ReportType.BANK
    assert builder.build_report("risk").report_type is ReportType.RISK
    with pytest.raises(ValueError, match="Report type"):
        builder.build_report("unknown")
    with pytest.raises(ValueError, match="required"):
        builder.build_report("client")
    with pytest.raises(ValueError, match="only"):
        builder.build_report("bank", client_id=alice.client_id)


def test_client_report_rejects_unknown_client(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, _, _ = reporting_context

    with pytest.raises(ClientNotFoundError, match="missing"):
        builder.build_client_report("missing")


def test_json_structure_and_standard_domain_serialization() -> None:
    builder = ReportBuilder(Bank("Empty"), clock=lambda: NOW)
    identifier = UUID("12345678-1234-5678-1234-567812345678")
    report = Report(
        ReportType.CLIENT,
        "UTF-8: отчёт",
        NOW,
        {
            "decimal": Decimal("10.50"),
            "enum": ClientStatus.ACTIVE,
            "uuid": identifier,
            "date": date(2026, 7, 17),
            "datetime": NOW,
        },
    )

    payload = json.loads(builder.to_json(report))

    assert payload == {
        "report_type": "client",
        "title": "UTF-8: отчёт",
        "generated_at": NOW.isoformat(),
        "data": {
            "decimal": "10.50",
            "enum": "active",
            "uuid": str(identifier),
            "date": "2026-07-17",
            "datetime": NOW.isoformat(),
        },
    }


def test_report_and_json_reject_invalid_values() -> None:
    builder = ReportBuilder(Bank(), clock=lambda: NOW)

    with pytest.raises(TypeError, match="ReportType"):
        Report("client", "Title", NOW)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mapping"):
        Report(ReportType.CLIENT, "Title", NOW, [])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Unsupported"):
        builder.to_json(Report(ReportType.CLIENT, "Title", NOW, {"value": object()}))
    with pytest.raises(ValueError):
        builder.to_json(Report(ReportType.CLIENT, "Title", NOW, {"value": float("nan")}))


def test_json_export_creates_parent_and_requires_explicit_overwrite(tmp_path: Path) -> None:
    builder = ReportBuilder(Bank("Банк"), clock=lambda: NOW)
    report = builder.build_bank_report()
    destination = tmp_path / "nested" / "bank.json"

    path = builder.export_to_json(report, destination)

    assert path == destination
    assert "Банк" in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        builder.export_to_json(report, destination)
    assert builder.export_to_json(report, destination, overwrite=True) == destination


def test_csv_has_stable_paths_utf8_and_creates_directory(tmp_path: Path) -> None:
    builder = ReportBuilder(Bank("Банк"), clock=lambda: NOW)
    report = builder.build_bank_report()

    path = builder.export_to_csv(report, tmp_path / "nested")
    rows = list(csv.reader(StringIO(path.read_text(encoding="utf-8"))))

    assert path.name == "bank_report.csv"
    assert rows[0] == ["field", "value"]
    assert rows[1] == ["report_type", "bank"]
    assert ["data.bank.name", "Банк"] in rows
    with pytest.raises(FileExistsError):
        builder.export_to_csv(report, path)


@pytest.mark.parametrize(
    ("method_name", "suffix"),
    (("export_to_json", ".json"), ("export_to_csv", ".csv")),
)
def test_export_rejects_wrong_suffix(
    method_name: str,
    suffix: str,
    tmp_path: Path,
) -> None:
    builder = ReportBuilder(Bank(), clock=lambda: NOW)
    report = builder.build_bank_report()

    with pytest.raises(ValueError, match=suffix.replace(".", r"\.")):
        getattr(builder, method_name)(report, tmp_path / "report.txt")


def test_chart_builders_return_all_three_figures(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, alice, _ = reporting_context
    figures = (
        builder.build_transaction_status_chart(),
        builder.build_client_activity_chart(),
        builder.build_balance_history_chart(alice.client_id),
    )
    try:
        assert all(isinstance(figure, Figure) for figure in figures)
        assert figures[0].axes[0].get_title() == "Transactions by status"
        assert figures[1].axes[0].get_title() == "Transactions by client"
        assert figures[2].axes[0].lines
    finally:
        for figure in figures:
            plt.close(figure)


def test_save_charts_creates_non_empty_pngs_and_closes_only_its_figures(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
    tmp_path: Path,
) -> None:
    builder, alice, _ = reporting_context
    sentinel = plt.figure()
    before = set(plt.get_fignums())
    try:
        paths = builder.save_charts(tmp_path / "charts", client_id=alice.client_id)

        assert {path.name for path in paths} == {
            "transaction_statuses.png",
            "client_activity.png",
            "balance_history.png",
        }
        assert all(path.exists() and path.stat().st_size > 0 for path in paths)
        assert all(plt.imread(path).size > 0 for path in paths)
        assert set(plt.get_fignums()) == before
    finally:
        plt.close(sentinel)


def test_save_charts_requires_explicit_overwrite(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
    tmp_path: Path,
) -> None:
    builder, _, _ = reporting_context

    first = builder.save_charts(tmp_path)
    with pytest.raises(FileExistsError):
        builder.save_charts(tmp_path)
    assert builder.save_charts(tmp_path, overwrite=True) == first


def test_empty_bank_and_missing_history_produce_valid_reports_and_charts(tmp_path: Path) -> None:
    builder = ReportBuilder(Bank("Empty"), clock=lambda: NOW)

    bank_report = builder.build_bank_report()
    risk_report = builder.build_risk_report()
    paths = builder.save_charts(tmp_path)

    assert bank_report.data["clients_count"] == 0
    assert bank_report.data["balances_by_currency"] == {}
    assert risk_report.data["analyzed_operations"] == 0
    assert risk_report.data["suspicious_operations"] == []
    assert all(path.stat().st_size > 0 for path in paths)


def test_client_without_accounts_or_operations_has_empty_sections() -> None:
    bank = Bank("Empty Client")
    client = bank.add_client(
        Client("No Accounts", 30, {"email": "none@example.com"}, "secret", client_id="none")
    )
    builder = ReportBuilder(bank, clock=lambda: NOW)

    report = builder.build_client_report(client.client_id)

    assert report.data["accounts"] == []
    assert report.data["transactions"]["total"] == 0
    assert report.data["suspicious_operations"] == []
    assert report.data["risk_profile"]["highest_risk_level"] is RiskLevel.LOW


def test_bank_public_reporting_accessors_are_scoped_to_the_bank() -> None:
    first_bank = Bank("First", clock=lambda: NOW)
    second_bank = Bank("Second", clock=lambda: NOW)
    client = Client(
        "Shared Client",
        30,
        {"email": "shared@example.com"},
        "secret",
        client_id="shared",
    )
    first_bank.add_client(client)
    second_bank.add_client(client)
    first_account = first_bank.open_account(client.client_id, account_id="FIRST")
    second_bank.open_account(client.client_id, account_id="SECOND")

    assert first_bank.clients == (client,)
    assert first_bank.accounts == (first_account,)
    assert first_bank.get_client(client.client_id) is client
    assert first_bank.get_account(first_account.account_number) is first_account
    assert first_bank.get_client_accounts(client.client_id) == (first_account,)
    assert first_bank.get_account_owner(first_account.account_number) is client


def test_client_ranking_never_combines_different_currencies() -> None:
    bank = Bank("Currencies", clock=lambda: NOW)
    client = bank.add_client(Client("Mixed Balance", 30, {"email": "mixed@example.com"}, "secret"))
    bank.open_account(client.client_id, account_id="RUB", balance=100, currency=Currency.RUB)
    bank.open_account(client.client_id, account_id="USD", balance=10, currency=Currency.USD)

    rankings = (
        ReportBuilder(bank, clock=lambda: NOW)
        .build_bank_report()
        .data["client_ranking_by_currency"]
    )

    assert rankings["RUB"][0]["balance"] == Decimal("100")
    assert rankings["USD"][0]["balance"] == Decimal("10")


def test_balance_history_uses_completed_settlement_amounts(
    reporting_context: tuple[ReportBuilder, Client, tuple[Transaction, ...]],
) -> None:
    builder, _, transactions = reporting_context

    assert transactions[0].received_amount == Decimal("1.00")
    assert transactions[2].received_amount is None
    figure = builder.build_balance_history_chart()
    try:
        final_values = {
            line.get_label(): line.get_ydata()[-1] for axis in figure.axes for line in axis.lines
        }
        assert final_values == {"RUB-1": Decimal("848.50"), "USD-1": Decimal("1.50")}
    finally:
        plt.close(figure)


@pytest.mark.parametrize(
    "arguments",
    (
        (object(),),
        (Bank(), [object()]),
    ),
)
def test_builder_rejects_invalid_domain_objects(arguments: tuple[object, ...]) -> None:
    with pytest.raises(TypeError):
        ReportBuilder(*arguments)  # type: ignore[arg-type]


def test_builder_rejects_transaction_from_another_bank_with_same_account_numbers() -> None:
    report_bank = Bank("Report", clock=lambda: NOW)
    other_bank = Bank("Other", clock=lambda: NOW)
    report_client = report_bank.add_client(
        Client("Report Client", 30, {"email": "report@example.com"}, "secret")
    )
    other_client = other_bank.add_client(
        Client("Other Client", 30, {"email": "other@example.com"}, "secret")
    )
    report_bank.open_account(report_client.client_id, account_id="SAME")
    other_sender = other_bank.open_account(other_client.client_id, account_id="SAME")
    other_recipient = other_bank.open_account(other_client.client_id, account_id="OTHER")
    foreign_transaction = Transaction(
        TransactionType.INTERNAL_TRANSFER,
        1,
        Currency.RUB,
        other_sender,
        other_recipient,
    )

    with pytest.raises(ValueError, match="registered"):
        ReportBuilder(report_bank, (foreign_transaction,))


def test_exports_reject_non_report_and_chart_file_destination(tmp_path: Path) -> None:
    builder = ReportBuilder(Bank(), clock=lambda: NOW)
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(TypeError, match="Report"):
        builder.export_to_json({}, tmp_path)  # type: ignore[arg-type]
    with pytest.raises(NotADirectoryError):
        builder.export_to_json(builder.build_bank_report(), file_path)
    with pytest.raises(NotADirectoryError):
        builder.save_charts(file_path)


def test_save_charts_validates_client_before_writing(tmp_path: Path) -> None:
    builder = ReportBuilder(Bank(), clock=lambda: NOW)
    destination = tmp_path / "charts"

    with pytest.raises(ClientNotFoundError):
        builder.save_charts(destination, client_id="missing")
    assert not destination.exists()
