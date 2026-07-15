# Banking System

Banking System is a Python package for modelling core banking operations. The planned scope includes customer and account management, transaction processing, audit trails, and reporting.

The project is in active development. It currently provides validated base, savings, premium,
and investment account models together with quality tooling.

## Package architecture

The source code uses a `src` layout and is divided into domain-oriented packages:

- `common` contains shared domain utilities;
- `accounts` contains the account model, account states, currencies, and operation errors;
- `clients` contains customer-related functionality;
- `bank` coordinates operations across domains;
- `transactions` contains transaction processing;
- `audit` contains audit trail functionality;
- `reports` contains reporting functionality.

The remaining packages define architectural boundaries only. Their domain models and services will be added as the project develops.

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

- Only account models and their in-memory operations are implemented.
- Persistence and external integrations are not available.
