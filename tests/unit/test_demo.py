from io import StringIO

from banking_system.audit import RiskLevel
from banking_system.demo import DemoResult, run_demo
from banking_system.transactions import TransactionStatus


def run_silently() -> DemoResult:
    return run_demo(stream=StringIO())


def test_demo_initializes_bank_clients_accounts_and_transactions() -> None:
    result = run_silently()

    assert result.bank.name == "Example Bank"
    assert len(result.clients) == 6
    assert len(result.accounts) == 12
    assert len(result.transactions) == 40
    assert len({transaction.transaction_id for transaction in result.transactions}) == 40
    assert all(len(client.account_numbers) == 2 for client in result.clients)
    assert {account.account_number for account in result.accounts} == {
        account_number for client in result.clients for account_number in client.account_numbers
    }


def test_demo_processes_successful_erroneous_and_risk_blocked_transactions() -> None:
    result = run_silently()

    assert result.statistics.total == 40
    assert result.statistics.completed == 32
    assert result.statistics.rejected == 8
    assert result.statistics.remaining_in_queue == 0
    assert all(
        transaction.status in {TransactionStatus.COMPLETED, TransactionStatus.FAILED}
        for transaction in result.transactions
    )
    assert result.statistics.errors.total_errors == 8
    assert result.statistics.errors.errors_by_type == {
        "InsufficientFundsError": 4,
        "RiskBlockedError": 4,
    }


def test_demo_logs_queue_completion_and_rejection_for_every_transaction() -> None:
    result = run_silently()
    records_by_event = {
        event_type: [record for record in result.event_log if record.event_type == event_type]
        for event_type in {
            "transaction_queued",
            "transaction_completed",
            "transaction_error",
        }
    }

    assert len(records_by_event["transaction_queued"]) == 40
    assert len(records_by_event["transaction_completed"]) == 32
    assert len(records_by_event["transaction_error"]) == 8
    assert {record.transaction_id for record in records_by_event["transaction_queued"]} == {
        transaction.transaction_id for transaction in result.transactions
    }
    assert result.statistics.queued == result.statistics.total


def test_demo_exposes_client_accounts_history_and_suspicious_operations() -> None:
    result = run_silently()
    selected_account_numbers = set(result.selected_client.account_numbers)

    assert {
        account.account_number for account in result.selected_accounts
    } == selected_account_numbers
    assert result.selected_history
    assert all(
        transaction.sender.account_number in selected_account_numbers
        or transaction.recipient.account_number in selected_account_numbers
        for transaction in result.selected_history
    )
    assert result.selected_suspicious_operations
    assert all(
        record.account_number in selected_account_numbers
        and record.details["risk_level"] in {RiskLevel.MEDIUM.value, RiskLevel.HIGH.value}
        for record in result.selected_suspicious_operations
    )
    assert result.statistics.suspicious == 8
    assert {record.details["risk_level"] for record in result.suspicious_operations} == {
        RiskLevel.MEDIUM.value,
        RiskLevel.HIGH.value,
    }


def test_demo_builds_top_three_statistics_and_total_balance_reports() -> None:
    result = run_silently()

    assert result.top_clients == tuple(result.bank.get_clients_ranking()[:3])
    assert [client.client_id for client, _ in result.top_clients] == [
        "client-005",
        "client-006",
        "client-003",
    ]
    assert result.statistics.completed + result.statistics.rejected == result.statistics.total
    assert result.total_balance == result.bank.get_total_balance()
    assert result.total_balance == 120_000


def test_demo_renders_every_public_scenario_and_report() -> None:
    stream = StringIO()

    run_demo(stream=stream)

    output = stream.getvalue()
    assert "[queued]" in output
    assert "[completed]" in output
    assert "[rejected]" in output
    assert "Accounts" in output
    assert "Transaction history" in output
    assert "Suspicious operations" in output
    assert "Top 3 clients" in output
    assert "Transaction statistics" in output
    assert "Total balance" in output
