# Banking System

Banking System is a Python package for modelling core banking operations. The planned scope includes customer and account management, transaction processing, audit trails, and reporting.

The project is in active development. It currently provides a validated bank account model and quality tooling.

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

- Only the base bank account model and its in-memory operations are implemented.
- Persistence and external integrations are not available.
