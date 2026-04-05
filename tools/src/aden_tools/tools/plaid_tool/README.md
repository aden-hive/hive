# Plaid Tool

Access bank accounts, balances, and transactions using the Plaid API.

## Tools

| Tool | Description |
|------|-------------|
| `plaid_get_accounts` | List linked bank accounts |
| `plaid_get_balance` | Get real-time account balances |
| `plaid_sync_transactions` | Sync new transactions incrementally |
| `plaid_get_transactions` | Get transactions with date range and filters |
| `plaid_get_institution` | Get details about a financial institution |
| `plaid_search_institutions` | Search for institutions by name |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `PLAID_CLIENT_ID` | Plaid client ID |
| `PLAID_SECRET` | Plaid secret key |
| `PLAID_ENV` | Environment: `sandbox`, `development`, or `production` (default: `sandbox`) |

Get credentials at: [Plaid Dashboard](https://dashboard.plaid.com/developers/keys)

## Usage Examples

### Get account balances
```python
plaid_get_balance(access_token="access-sandbox-abc123")
```

### Get recent transactions
```python
plaid_get_transactions(
    access_token="access-sandbox-abc123",
    start_date="2026-01-01",
    end_date="2026-01-31",
    count=50,
)
```

### Search for a bank
```python
plaid_search_institutions(query="Chase", count=5)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "PLAID_CLIENT_ID and PLAID_SECRET not set", "help": "Get credentials at https://dashboard.plaid.com/developers/keys"}
{"error": "Plaid API error: INVALID_ACCESS_TOKEN"}
{"error": "Request timed out"}
```
