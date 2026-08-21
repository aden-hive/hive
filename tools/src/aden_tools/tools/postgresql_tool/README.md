# PostgreSQL Tool

Execute SQL queries and transactions against a PostgreSQL database for operational business workflows.

---

## Features

- **`run_postgres_query`**: Execute read-only SQL queries with SQL-level row limit enforcement  
- **`run_postgres_transaction`**: Execute multiple SQL statements atomically  
- **`list_postgres_tables`**: List tables in the public schema  
- **`describe_postgres_table`**: Inspect table column definitions  
- **`postgres_health_check`**: Verify database connectivity  

---

## Setup

### 1. Install Dependencies

The PostgreSQL tool requires `psycopg` (v3):

```bash
pip install psycopg[binary]
```

---

### 2. Configure Credentials

You can configure credentials using either Hive’s credential store or environment variables.

#### Option A: Hive Credential Store (Recommended for Production)

Credential keys:

- `postgres_host`
- `postgres_port`
- `postgres_database`
- `postgres_username`
- `postgres_password`
- `postgres_ssl_mode`

---

#### Option B: Environment Variables

```bash
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DATABASE="my_database"
export POSTGRES_USERNAME="my_user"
export POSTGRES_PASSWORD="my_password"
export POSTGRES_SSL_MODE="prefer"
```

---

## Usage

### Run a Read-Only Query

```python
result = run_postgres_query(
    sql="SELECT id, email FROM users ORDER BY created_at DESC",
    max_rows=100
)

if result.get("success"):
    for row in result["rows"]:
        print(row)
else:
    print(f"Error: {result['error']}")
```

---

### Execute an Atomic Transaction

```python
result = run_postgres_transaction([
    "UPDATE accounts SET balance = balance - 100 WHERE id = 1",
    "UPDATE accounts SET balance = balance + 100 WHERE id = 2"
])

if result.get("success"):
    print(f"Statements executed: {result['statements_executed']}")
else:
    print(f"Error: {result['error']}")
```

---

### List Tables

```python
result = list_postgres_tables()

if result.get("success"):
    print(result["tables"])
```

---

### Describe a Table

```python
result = describe_postgres_table("users")

if result.get("success"):
    for col in result["columns"]:
        print(col)
```

---

### Health Check

```python
result = postgres_health_check()

if result.get("success"):
    print(result["message"])
```

---

## Safety Features

### Read-Only Enforcement

`run_postgres_query` blocks write operations.  
The following SQL keywords are rejected:

- `INSERT`
- `UPDATE`
- `DELETE`
- `DROP`
- `CREATE`
- `ALTER`
- `TRUNCATE`
- `MERGE`
- `REPLACE`
- `GRANT`
- `REVOKE`

---

### Destructive Operation Protection

`run_postgres_transaction` blocks:

- `DROP`
- `TRUNCATE`
- `ALTER`

to prevent schema-level destructive changes.

---

### SQL-Level Row Limits

- Default limit: 1000 rows  
- Maximum limit: 10,000 rows  
- If no `LIMIT` clause is provided, one is automatically appended  
- Results include `query_truncated: true` when row limiting is applied  

---

### Statement Timeout

- Default timeout: 30 seconds  
- Configurable per call  
- Prevents long-running queries from blocking agents  

---

### Automatic Rollback

If any statement in a transaction fails:

- The entire transaction is rolled back  
- No partial updates occur  

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_HOST` | Yes | Database host |
| `POSTGRES_PORT` | No | Database port (default: 5432) |
| `POSTGRES_DATABASE` | Yes | Database name |
| `POSTGRES_USERNAME` | Yes | Database username |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_SSL_MODE` | No | SSL mode (`disable`, `prefer`, `require`, etc.) |

---

## Error Handling

The tool returns structured error responses:

```python
# Write blocked in read-only mode
{
    "error": "Write operations are not allowed",
    "help": "Use run_postgres_transaction for write operations."
}

# Dependency missing
{
    "error": "psycopg is required for PostgreSQL tools.",
    "help": "Install dependency: pip install psycopg[binary]"
}

# Transaction failure
{
    "error": "Transaction failed and was rolled back: ..."
}
```

---

## Example Agent Use Cases

### Financial Reconciliation Agent

```python
run_postgres_query("""
    SELECT order_id, amount
    FROM ledger
    WHERE reconciliation_status = 'pending'
""")
```

---

### Order Processing Workflow

```python
run_postgres_transaction([
    "INSERT INTO orders (...) VALUES (...)",
    "UPDATE inventory SET quantity = quantity - 1 WHERE product_id = 42"
])
```

---

### Audit Logging

```python
run_postgres_transaction([
    "INSERT INTO audit_logs (event, created_at) VALUES ('order_created', NOW())"
])
```

---

## Extending the Tool

Future enhancements (not in MVP):

- Connection pooling  
- Query cost estimation  
- Pagination helpers  
- Prepared statement helpers  
- Schema introspection across multiple schemas  
- Role-based safety policies  

---

## Troubleshooting

### "psycopg is required"

Install dependency:

```bash
pip install psycopg[binary]
```

### Connection failed

- Verify host and port  
- Confirm credentials are correct  
- Ensure SSL configuration matches server requirements  

### Permission denied

- Confirm database user has required privileges  
- Verify schema access permissions  