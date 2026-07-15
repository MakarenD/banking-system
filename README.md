# Banking System

Banking System is a Python package for modelling core banking operations.

The project is in active development. It currently provides validated client and account models,
specialized account types, in-memory bank orchestration, and queued transaction processing.

## Package architecture

The source code uses a `src` layout and is divided into domain-oriented packages:

- `common` contains shared domain utilities;
- `accounts` contains the account model, account states, currencies, and operation errors;
- `clients` contains customer-related functionality;
- `bank` coordinates operations across domains;
- `transactions` contains transfer models, queues, currency conversion, and processing;
- `audit` contains audit trail functionality;
- `reports` contains reporting functionality.

The `common`, `audit`, and `reports` packages currently define architectural boundaries only.

## Accounts

`AbstractAccount` defines the shared account interface for deposits, withdrawals, and account information. `BankAccount` is its concrete implementation and supports balances in RUB, USD, EUR, KZT, and CNY. New accounts are active by default and receive an eight-character UUID-based identifier when one is not provided. Deposits and withdrawals accept positive finite numeric amounts and return the updated `Decimal` balance.

```python
from banking_system.accounts import BankAccount, Currency

account = BankAccount("Alice", balance=1_000, currency=Currency.USD)
account.deposit(250)
account.withdraw(100)

print(account.balance)  # Decimal("1150")
```

Frozen and closed accounts reject deposits and withdrawals with `AccountFrozenError` and `AccountClosedError`. A withdrawal that exceeds the available balance raises `InsufficientFundsError`.

### Specialized accounts

`SavingsAccount` preserves a configurable minimum balance. Its monthly interest rate is a
decimal fraction, so `Decimal("0.01")` represents 1%. Calling `apply_monthly_interest()` applies
one month of interest to the current balance.

`PremiumAccount` supports a configurable per-withdrawal limit and overdraft. Each successful
withdrawal charges its fixed fee in addition to the requested amount.

`InvestmentAccount` maintains virtual positions in stocks, bonds, and ETFs separately from its
cash balance. Position values and yearly growth rates are supplied as mappings. Growth rates are
decimal fractions, and `project_yearly_growth()` returns the projected gain across the portfolio.

```python
from decimal import Decimal

from banking_system.accounts import InvestmentAccount, PremiumAccount, SavingsAccount

savings = SavingsAccount(
    "Alice",
    balance=1_000,
    min_balance=250,
    monthly_interest_rate=Decimal("0.01"),
)
savings.apply_monthly_interest()

premium = PremiumAccount(
    "Bob",
    balance=500,
    withdrawal_limit=10_000,
    overdraft_limit=2_000,
    fixed_fee=25,
)
premium.withdraw(1_000)  # Decimal("-525")

investment = InvestmentAccount(
    "Carol",
    portfolio={"stocks": 1_000, "bonds": 500, "etf": 250},
    yearly_growth_rates={"stocks": 0.1, "bonds": 0.05, "etf": -0.2},
)
investment.project_yearly_growth()  # Decimal("75.00")
```

## Clients and bank operations

`Client` stores a validated full name, age, identifier, contacts, account numbers, and access
status. Clients must be at least 18 years old. `Bank` registers clients, opens accounts, manages
account states, authenticates clients, and searches accounts by number or client name.

```python
from banking_system.accounts import SavingsAccount
from banking_system.bank import Bank
from banking_system.clients import Client

bank = Bank("Example Bank")
client = Client(
    "Alice Smith",
    30,
    {"email": "alice@example.com"},
    "correct-password",
    client_id="client-1",
)
bank.add_client(client)

account = bank.open_account(
    client.client_id,
    SavingsAccount,
    balance=1_000,
    min_balance=250,
)
bank.freeze_account(account.account_number)
bank.unfreeze_account(account.account_number)

assert bank.authenticate_client(client.client_id, "correct-password")
assert bank.search_accounts("alice") == [account]
```

Three consecutive failed authentication attempts block the client and mark the activity as
suspicious. Account-opening, closing, freezing, and unfreezing operations are unavailable from
00:00 up to 05:00 local bank time; a restricted attempt also marks the client activity as
suspicious. Search, authentication, and balance reports remain available during that interval.

`get_total_balance()` returns the nominal `Decimal` sum across registered accounts.
`get_clients_ranking()` returns `(Client, Decimal)` pairs ordered by the same nominal balance.
Balances in different currencies are not converted.

## Transactions

`Transaction` represents an internal or external transfer between two accounts. Transactions
start in the pending state and retain their commission, processing attempts, failure reason, and
creation, update, and completion timestamps. `TransactionQueue` supports integer priorities,
with larger values processed first, delayed availability, FIFO ordering for equal priorities,
and cancellation.

`TransactionProcessor` applies a configurable percentage fee to external transfers, converts the
amount deposited into the recipient account with explicit `Decimal` exchange rates, retries
failed operations, and records each processing error. A standard account cannot transfer more
than its available balance, while `PremiumAccount` can use its configured overdraft. Frozen or
closed accounts cannot send or receive transfers.

```python
from decimal import Decimal

from banking_system.accounts import BankAccount, Currency
from banking_system.transactions import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionType,
)

sender = BankAccount("Alice", balance=1_000, currency=Currency.USD)
recipient = BankAccount("Bob", currency=Currency.EUR)
transaction = Transaction(
    TransactionType.EXTERNAL_TRANSFER,
    100,
    Currency.USD,
    sender,
    recipient,
)

queue = TransactionQueue()
queue.add(transaction, priority=10)
processor = TransactionProcessor(
    exchange_rates={(Currency.USD, Currency.EUR): Decimal("0.92")},
    external_fee_rate=Decimal("0.01"),
)
processor.process_queue(queue)

assert transaction.commission == Decimal("1.00")
assert recipient.balance == Decimal("92.00")
```

## Requirements

- Python 3.12 or later
- `pip`

## Virtual environment

Create and activate an isolated environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## Installation

Install the package in editable mode and add the development tools:

```bash
python -m pip install --editable .
python -m pip install --requirement requirements-dev.txt
```

The project currently has no third-party runtime dependencies.

## Tests

Run the test suite with:

```bash
pytest
```

## Code quality

Check formatting and lint rules with:

```bash
ruff format --check .
ruff check .
```

Apply Ruff formatting with:

```bash
ruff format .
```

## Current limitations

- Client, account, and bank orchestration state is in memory only.
- Cross-currency conversion is not available for totals or client rankings.
- Persistence and external integrations are not available.
