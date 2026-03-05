# CSV Tool

Read, write, and query CSV files with SQL support via DuckDB.

## Features

- **csv_read** - Read CSV file contents with pagination
- **csv_write** - Create new CSV files
- **csv_append** - Append rows to existing CSV files
- **csv_info** - Get CSV metadata without loading all data
- **csv_sql** - Query CSV files using SQL (powered by DuckDB)

## Setup

No API keys required. Files are accessed within the session sandbox.

For SQL queries, DuckDB must be installed:
```bash
pip install duckdb
# or
uv pip install tools[sql]
```

## Usage Examples

### Read a CSV File
```python
csv_read(
    path="data/sales.csv",
    workspace_id="ws_123",
    agent_id="agent_1",
    session_id="session_1",
    limit=100,
    offset=0
)
```

### Write a New CSV
```python
csv_write(
    path="output/report.csv",
    workspace_id="ws_123",
    agent_id="agent_1",
    session_id="session_1",
    columns=["name", "email", "score"],
    rows=[
        {"name": "Alice", "email": "alice@example.com", "score": 95},
        {"name": "Bob", "email": "bob@example.com", "score": 87}
    ]
)
```

### Append Rows
```python
csv_append(
    path="data/log.csv",
    workspace_id="ws_123",
    agent_id="agent_1",
    session_id="session_1",
    rows=[
        {"timestamp": "2024-01-15", "event": "login", "user": "alice"}
    ]
)
```

### Get File Info
```python
csv_info(
    path="data/large_file.csv",
    workspace_id="ws_123",
    agent_id="agent_1",
    session_id="session_1"
)
# Returns: columns, row count, file size (without loading all data)
```

### Query with SQL
```python
csv_sql(
    path="data/sales.csv",
    workspace_id="ws_123",
    agent_id="agent_1",
    session_id="session_1",
    query="SELECT category, SUM(amount) as total FROM data GROUP BY category ORDER BY total DESC"
)
```

## API Reference

### csv_read

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | Yes | Path to CSV file (relative to sandbox) |
| workspace_id | str | Yes | Workspace identifier |
| agent_id | str | Yes | Agent identifier |
| session_id | str | Yes | Session identifier |
| limit | int | No | Max rows to return (None = all) |
| offset | int | No | Rows to skip (default: 0) |

### csv_write

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | Yes | Path for new CSV file |
| workspace_id | str | Yes | Workspace identifier |
| agent_id | str | Yes | Agent identifier |
| session_id | str | Yes | Session identifier |
| columns | list[str] | Yes | Column names for header |
| rows | list[dict] | Yes | Row data as dictionaries |

### csv_append

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | Yes | Path to existing CSV file |
| workspace_id | str | Yes | Workspace identifier |
| agent_id | str | Yes | Agent identifier |
| session_id | str | Yes | Session identifier |
| rows | list[dict] | Yes | Rows to append |

### csv_info

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | Yes | Path to CSV file |
| workspace_id | str | Yes | Workspace identifier |
| agent_id | str | Yes | Agent identifier |
| session_id | str | Yes | Session identifier |

### csv_sql

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | str | Yes | Path to CSV file |
| workspace_id | str | Yes | Workspace identifier |
| agent_id | str | Yes | Agent identifier |
| session_id | str | Yes | Session identifier |
| query | str | Yes | SQL query (table name is `data`) |

## SQL Query Examples
```sql
-- Filter rows
SELECT * FROM data WHERE status = 'pending'

-- Aggregate data
SELECT category, COUNT(*) as count, AVG(price) as avg_price 
FROM data GROUP BY category

-- Sort and limit
SELECT name, price FROM data ORDER BY price DESC LIMIT 5

-- Case-insensitive search
SELECT * FROM data WHERE LOWER(name) LIKE '%phone%'
```

**Note:** Only SELECT queries are allowed for security.

## Error Handling
```python
{"error": "File not found: path/to/file.csv"}
{"error": "File must have .csv extension"}
{"error": "CSV file is empty or has no headers"}
{"error": "CSV parsing error: ..."}
{"error": "File encoding error: unable to decode as UTF-8"}
{"error": "DuckDB not installed. Install with: uv pip install duckdb"}
{"error": "Only SELECT queries are allowed for security reasons"}
```
