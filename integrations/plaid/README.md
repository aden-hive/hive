# Plaid Banking Integration

## Supported Operations
- Fetch account balances
- Retrieve transaction history
- Reconcile with GL entries
- Institution metadata lookup

## Configuration
- PLAID_CLIENT_ID
- PLAID_SECRET
- PLAID_ENV
- PLAID_ACCESS_TOKEN

## Usage
...
from integrations.plaid import create_plaid_connector_from_env

connector = create_plaid_connector_from_env()

# Fetch accounts
accounts = connector.fetch_accounts()

# Fetch transactions
transactions = connector.fetch_transactions(
    start_date="2024-01-01",
    end_date="2024-01-31"
)

# Reconcile with GL
report = connector.reconcile_with_gl(gl_entries=[
    {'amount': 100.00, 'date': '2024-01-15', 'description': 'Vendor payment'}
])

## Security
- Uses Plaid's official Python SDK
- Read-only access by default
- Secure token management via Hive credential store
- Supports sandbox, development, and production environments

## API Coverage
- /accounts/get - Account balances
- /transactions/get - Transaction history
- /institutions/get_by_id - Institution metadata
- Reconciliation engine for GL matching

## Prerequisites
pip install plaid-python

## Links
- [Plaid Documentation](https://plaid.com/docs)
- [Plaid Dashboard](https://dashboard.plaid.com)