# Databricks Tool

Execute SQL queries and explore tables in Databricks SQL Warehouses and Unity Catalog.

## Features

- **`run_databricks_sql`**: Execute read-only SQL queries and return structured results
- **`describe_databricks_table`**: Get column names, types, and metadata for a Unity Catalog table

## Setup

### 1. Install Dependencies

The Databricks tool requires `databricks-sdk`:

```bash
pip install databricks-sdk>=0.20.0
```

### 2. Configure Authentication

#### Personal Access Token (Recommended)

1. Log in to your Databricks workspace
2. Click your username → **Settings** → **Developer** → **Access tokens**
3. Click **Generate new token**, give it a name (e.g., "Hive Agent")
4. Copy the token and set it:

```bash
export DATABRICKS_TOKEN="dapi..."
export DATABRICKS_HOST="adb-12345.6.azuredatabricks.net"
```

### 3. Set SQL Warehouse ID (Optional)

If your queries don't specify a warehouse ID, set a default:

```bash
export DATABRICKS_WAREHOUSE_ID="abc123def456"
```

## Usage

### Run a Query

```python
result = run_databricks_sql(
    sql="SELECT name, COUNT(*) as count FROM main.default.users GROUP BY name",
    max_rows=100
)

if result.get("success"):
    for row in result["rows"]:
        print(row)
else:
    print(f"Error: {result['error']}")
```

### Describe a Table

```python
result = describe_databricks_table(
    table_name="main.default.users"
)

if result.get("success"):
    for col in result["columns"]:
        print(f"  - {col['name']}: {col['type']}")
else:
    print(f"Error: {result['error']}")
```

## Safety Features

### Read-Only Enforcement

The tool blocks write operations for safety. The following SQL keywords are rejected:

- `INSERT`
- `UPDATE`
- `DELETE`
- `DROP`
- `CREATE`
- `ALTER`
- `TRUNCATE`
- `MERGE`
- `REPLACE`

### Row Limits

- Default limit: 1000 rows
- Maximum limit: 10,000 rows
- Results include `query_truncated: true` if more rows exist

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABRICKS_TOKEN` | Yes | Personal Access Token for authentication |
| `DATABRICKS_HOST` | Yes | Workspace hostname (e.g., `adb-12345.6.azuredatabricks.net`) |
| `DATABRICKS_WAREHOUSE_ID` | No | Default SQL Warehouse ID for queries |

## Error Handling

The tool returns structured error responses with helpful messages:

```python
# Authentication error
{
    "error": "Databricks authentication failed",
    "help": "Check that your DATABRICKS_TOKEN is valid and not expired."
}

# Permission error
{
    "error": "Databricks permission denied: ...",
    "help": "Ensure your token has the required permissions..."
}

# Write operation blocked
{
    "error": "Write operations are not allowed",
    "help": "Only SELECT queries are permitted."
}
```

## Example Agent Use Cases

### Data Analytics Copilot

```python
# Agent receives: "What are the top selling products this quarter?"

# Step 1: Explore the table
describe_databricks_table("main.sales.transactions")

# Step 2: Run the query
run_databricks_sql("""
    SELECT product_name, SUM(revenue) as total_revenue
    FROM main.sales.transactions
    WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), 90)
    GROUP BY product_name
    ORDER BY total_revenue DESC
    LIMIT 10
""")
```

### Data Quality Monitor

```python
# Check for data quality issues
run_databricks_sql("""
    SELECT
        COUNT(*) as total_rows,
        COUNT_IF(email IS NULL) as null_emails,
        COUNT_IF(NOT email RLIKE '^[^@]+@[^@]+$') as invalid_emails
    FROM main.default.users
""")
```

## Troubleshooting

### "DATABRICKS_TOKEN is not set"

- Generate a Personal Access Token in your Databricks workspace settings
- Set the `DATABRICKS_TOKEN` environment variable

### "DATABRICKS_HOST is not set"

- Set `DATABRICKS_HOST` to your workspace hostname (without `https://`)
- Example: `adb-12345678901234.5.azuredatabricks.net`

### "Permission denied"

- Ensure your token has access to the SQL Warehouse
- Verify you have `SELECT` privileges on the target tables

### "Table not found"

- Use fully qualified names: `catalog.schema.table`
- Verify the catalog, schema, and table exist in Unity Catalog
