# Banking System

Banking System is a Python package for modelling core banking operations. The planned scope includes customer and account management, transaction processing, audit trails, and reporting.

The project is in active development. It currently provides the package structure and quality tooling; banking business logic has not been implemented yet.

## Package architecture

The source code uses a `src` layout and is divided into domain-oriented packages:

- `common` contains shared domain utilities;
- `accounts` contains account-related functionality;
- `clients` contains customer-related functionality;
- `bank` coordinates operations across domains;
- `transactions` contains transaction processing;
- `audit` contains audit trail functionality;
- `reports` contains reporting functionality.

These packages define architectural boundaries only. Their domain models and services will be added as the project develops.

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

- Domain models and banking operations are not implemented.
- Persistence and external integrations are not available.
- The test suite currently verifies only that the package can be imported.
