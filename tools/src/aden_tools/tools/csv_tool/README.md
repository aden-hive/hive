# CSV Tool

Read, write, and query CSV files with SQL support.

## Description

Provides comprehensive CSV file operations including reading with pagination, writing new files, appending rows, querying with SQL (powered by DuckDB), and retrieving file metadata. All operations are sandboxed to the session workspace.

## Functions

### csv_read

Read CSV file contents with pagination support.

#### Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | Path to CSV file (relative to session sandbox) |
| `workspace_id` | str | Yes | - | Workspace identifier |
| `agent_id` | str | Yes | - | Agent identifier |
| `session_id` | str | Yes | - | Session identifier |
| `limit` | int | No | `None` | Maximum rows to return (None = all rows) |
| `offset` | int | No | `0` | Number of rows to skip from beginning |

#### Returns

```python
{
    "success": True,
    "path": "data.csv",
    "columns": ["id", "name", "price"],
    "column_count": 3,
    "rows": [{"id": "1", "name": "Item", "price": "100"}],
    "row_count": 1,
    "total_rows": 100,
    "offset": 0,
    "limit": None
}
```

---

### csv_write

Write data to a new CSV file.

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | str | Yes | Path to CSV file (relative to session sandbox) |
| `workspace_id` | str | Yes | Workspace identifier |
| `agent_id` | str | Yes | Agent identifier |
| `session_id` | str | Yes | Session identifier |
| `columns` | List[str] | Yes | Column names for the header |
| `rows` | List[dict] | Yes | Rows as list of dictionaries |

#### Returns

```python
{
    "success": True,
    "path": "output.csv",
    "columns": ["name", "age"],
    "column_count": 2,
    "rows_written": 5
}
```

---

### csv_append

Append rows to an existing CSV file.

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | str | Yes | Path to existing CSV file |
| `workspace_id` | str | Yes | Workspace identifier |
| `agent_id` | str | Yes | Agent identifier |
| `session_id` | str | Yes | Session identifier |
| `rows` | List[dict] | Yes | Rows to append (keys must match existing columns) |

#### Returns

```python
{
    "success": True,
    "path": "data.csv",
    "rows_appended": 3,
    "total_rows": 103
}
```

---

### csv_info

Get CSV file metadata without reading all data.

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | str | Yes | Path to CSV file |
| `workspace_id` | str | Yes | Workspace identifier |
| `agent_id` | str | Yes | Agent identifier |
| `session_id` | str | Yes | Session identifier |

#### Returns

```python
{
    "success": True,
    "path": "data.csv",
    "columns": ["id", "name", "price"],
    "column_count": 3,
    "total_rows": 1000,
    "file_size_bytes": 50432
}
```

---

### csv_sql

Query CSV files using SQL (powered by DuckDB).

The CSV file is loaded as a table named `data`. Use standard SQL syntax for queries.

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | str | Yes | Path to CSV file |
| `workspace_id` | str | Yes | Workspace identifier |
| `agent_id` | str | Yes | Agent identifier |
| `session_id` | str | Yes | Session identifier |
| `query` | str | Yes | SQL SELECT query (table name is 'data') |

#### Returns

```python
{
    "success": True,
    "path": "sales.csv",
    "query": "SELECT category, SUM(price) as total FROM data GROUP BY category",
    "columns": ["category", "total"],
    "column_count": 2,
    "rows": [{"category": "Electronics", "total": 5000}],
    "row_count": 1
}
```

## Example Usage

### Basic Reading

```python
# Read entire CSV
result = csv_read(
    path="products.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789"
)

# Read with pagination
result = csv_read(
    path="large_dataset.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    limit=100,
    offset=0
)
```

### Writing and Appending

```python
# Create new CSV
csv_write(
    path="users.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    columns=["name", "email", "age"],
    rows=[
        {"name": "Alice", "email": "alice@example.com", "age": "30"},
        {"name": "Bob", "email": "bob@example.com", "age": "25"}
    ]
)

# Append more rows
csv_append(
    path="users.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    rows=[
        {"name": "Charlie", "email": "charlie@example.com", "age": "35"}
    ]
)
```

### SQL Queries

```python
# Filter rows
csv_sql(
    path="orders.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    query="SELECT * FROM data WHERE status = 'pending' AND price > 100"
)

# Aggregate data
csv_sql(
    path="sales.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    query="SELECT region, COUNT(*) as count, AVG(revenue) as avg_revenue FROM data GROUP BY region"
)

# Sort and limit
csv_sql(
    path="products.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    query="SELECT name, price FROM data ORDER BY price DESC LIMIT 10"
)

# Text search (case-insensitive)
csv_sql(
    path="inventory.csv",
    workspace_id="ws_123",
    agent_id="agent_456",
    session_id="sess_789",
    query="SELECT * FROM data WHERE LOWER(name) LIKE '%laptop%'"
)
```

## SQL Support

### Requirements

Install DuckDB dependency:
```bash
pip install duckdb
# or
pip install tools[sql]
```

### Security

- **Only SELECT queries** are allowed
- **Blocked keywords**: INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, EXEC, EXECUTE
- Queries execute in isolated in-memory DuckDB instance
- Files are sandboxed to session workspace

### DuckDB SQL Syntax

The CSV is available as table `data`. Supports:
- Standard SQL: SELECT, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT
- Aggregates: COUNT(), SUM(), AVG(), MIN(), MAX()
- String functions: LOWER(), UPPER(), LIKE, SUBSTRING()
- Joins: Self-joins with aliases (`FROM data d1 JOIN data d2 ON ...`)
- CTEs: `WITH temp AS (...) SELECT * FROM temp`

## Limitations

- **Encoding**: Files must be UTF-8 encoded
- **File Extension**: Must end with `.csv`
- **Headers**: First row must contain column names
- **Memory**: Large files (>100MB) may cause memory issues
- **Sandboxing**: All paths are relative to session workspace

## Error Handling

Common errors returned:
- `File not found` - CSV file doesn't exist
- `File must have .csv extension` - Invalid file extension
- `CSV file is empty or has no headers` - Missing or empty header row
- `File encoding error: unable to decode as UTF-8` - Non-UTF-8 file
- `DuckDB not installed` - Missing duckdb package for csv_sql
- `Only SELECT queries are allowed` - Attempted non-SELECT query
- `Query failed: ...` - SQL syntax error or execution failure
