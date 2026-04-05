# Snowflake Tool

SQL statement execution and async query management via the Snowflake REST API v2.

## Tools

| Tool | Description |
|------|-------------|
| `snowflake_execute_sql` | Execute a SQL statement and return results |
| `snowflake_get_statement_status` | Poll the status and results of an async query |
| `snowflake_cancel_statement` | Cancel a running SQL statement |

## Setup

Requires a Snowflake account identifier and an OAuth or JWT access token:

1. Note your **Account Identifier** (e.g. `orgname-accountname` or `xy12345.us-east-1`)
2. Generate an access token via OAuth, key-pair authentication, or Snowflake programmatic access

```bash
SNOWFLAKE_ACCOUNT=orgname-accountname
SNOWFLAKE_TOKEN=your-oauth-or-jwt-token
```

Optional — set default context to avoid repeating them per query:

```bash
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=MY_DATABASE
SNOWFLAKE_SCHEMA=PUBLIC
SNOWFLAKE_TOKEN_TYPE=OAUTH
```

> `SNOWFLAKE_TOKEN_TYPE` defaults to `OAUTH`. Set to `KEYPAIR_JWT` if using key-pair auth.

## Usage Examples

### Run a simple query

```python
snowflake_execute_sql(statement="SELECT CURRENT_USER(), CURRENT_DATABASE()")
```

### Query a specific database and schema

```python
snowflake_execute_sql(
    statement="SELECT * FROM orders WHERE status = 'pending' LIMIT 100",
    database="SALES_DB",
    schema="PUBLIC",
    warehouse="COMPUTE_WH",
)
```

### Run a long query asynchronously

```python
# Returns immediately with status="running"
result = snowflake_execute_sql(
    statement="SELECT COUNT(*) FROM very_large_table",
    timeout=120,
)

# Poll until complete
snowflake_get_statement_status(
    statement_handle=result["statement_handle"]
)
```

### Cancel a running query

```python
snowflake_cancel_statement(
    statement_handle="01abc123-0000-0001-0000-000100020003"
)
```

## Response Format

A completed query returns:

```python
{
    "statement_handle": "01abc...",
    "status": "complete",
    "num_rows": 42,
    "columns": ["ID", "NAME", "CREATED_AT"],
    "rows": [["1", "Alice", "2024-01-01"], ...],
    "truncated": False,  # True if > 100 rows returned
}
```

An async query in progress returns:

```python
{
    "statement_handle": "01abc...",
    "status": "running",
    "message": "Asynchronous execution in progress",
}
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "SNOWFLAKE_ACCOUNT and SNOWFLAKE_TOKEN are required", "help": "Set SNOWFLAKE_ACCOUNT and SNOWFLAKE_TOKEN environment variables"}
{"error": "HTTP 422: Query failed"}
{"error": "statement is required"}
```
