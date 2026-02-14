# CSV Tool

Read, write, append, query, and inspect CSV files.

## Description

This tool provides CSV file manipulation within agent session sandboxes. It includes reading with pagination, writing new files, appending rows, getting file metadata, and querying CSV data using SQL.

## All Tools (5 Total)

### File Operations (4)
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `csv_read` | Read CSV file with optional pagination | `path`, `limit`, `offset` |
| `csv_write` | Create new CSV file from data | `path`, `columns`, `rows` |
| `csv_append` | Append rows to existing CSV | `path`, `rows` |
| `csv_info` | Get CSV metadata (columns, row count, file size) | `path` |

### Advanced (1)
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `csv_sql` | Query CSV using SQL (requires DuckDB) | `path`, `query` |

## Security

All CSV operations are sandboxed to the agent's session directory using `get_secure_path()`. Paths are relative to:
```
~/.hive/workspaces/{workspace_id}/agents/{agent_id}/sessions/{session_id}/
```

## Examples

### Reading a CSV with Pagination
```python
# Read first 100 rows
result = csv_read(
    path="data/customers.csv",
    workspace_id="ws_123",
    agent_id="ag_456",
    session_id="sess_789",
    limit=100,
    offset=0
)

# Returns:
{
    "success": True,
    "path": "data/customers.csv",
    "columns": ["id", "name", "email"],
    "column_count": 3,
    "rows": [...],  # List of dicts
    "row_count": 100,
    "total_rows": 5432,
    "offset": 0,
    "limit": 100
}
```

### Writing a New CSV
```python
result = csv_write(
    path="output/report.csv",
    workspace_id="ws_123",
    agent_id="ag_456",
    session_id="sess_789",
    columns=["date", "revenue", "customers"],
    rows=[
        {"date": "2024-01-01", "revenue": "1000", "customers": "25"},
        {"date": "2024-01-02", "revenue": "1200", "customers": "28"}
    ]
)

# Returns:
{
    "success": True,
    "path": "output/report.csv",
    "columns": ["date", "revenue", "customers"],
    "column_count": 3,
    "rows_written": 2
}
```

### Appending to an Existing CSV
```python
result = csv_append(
    path="output/report.csv",
    workspace_id="ws_123",
    agent_id="ag_456",
    session_id="sess_789",
    rows=[
        {"date": "2024-01-03", "revenue": "1500", "customers": "32"}
    ]
)

# Returns:
{
    "success": True,
    "path": "output/report.csv",
    "rows_appended": 1,
    "total_rows": 3
}
```

### Getting CSV Metadata
```python
result = csv_info(
    path="data/customers.csv",
    workspace_id="ws_123",
    agent_id="ag_456",
    session_id="sess_789"
)

# Returns:
{
    "success": True,
    "path": "data/customers.csv",
    "columns": ["id", "name", "email", "created_at"],
    "column_count": 4,
    "total_rows": 5432,
    "file_size_bytes": 245678
}
```

### Querying with SQL
```python
# Requires DuckDB: uv pip install duckdb
result = csv_sql(
    path="data/sales.csv",
    workspace_id="ws_123",
    agent_id="ag_456",
    session_id="sess_789",
    query="SELECT category, COUNT(*) as count, AVG(price) as avg_price FROM data WHERE date >= '2024-01-01' GROUP BY category ORDER BY avg_price DESC"
)

# Returns:
{
    "success": True,
    "path": "data/sales.csv",
    "query": "SELECT category, COUNT(*) as count...",
    "columns": ["category", "count", "avg_price"],
    "column_count": 3,
    "rows": [
        {"category": "Electronics", "count": 150, "avg_price": 299.99},
        {"category": "Books", "count": 320, "avg_price": 24.99}
    ],
    "row_count": 2
}
```

**Note:** The CSV is loaded as a table named `data`. Use this in your queries:
```sql
SELECT * FROM data WHERE price > 100
SELECT category, SUM(amount) as total FROM data GROUP BY category
SELECT * FROM data WHERE LOWER(name) LIKE '%phone%'
```

## Error Handling

All tools return error dictionaries on failure:

- `{"error": "File not found: path"}` - CSV file doesn't exist
- `{"error": "File must have .csv extension"}` - Invalid file extension
- `{"error": "CSV file is empty or has no headers"}` - Missing headers
- `{"error": "CSV parsing error: ..."}` - Malformed CSV
- `{"error": "File encoding error: unable to decode as UTF-8"}` - Encoding issue
- `{"error": "offset and limit must be non-negative"}` - Invalid pagination parameters
- `{"error": "columns cannot be empty"}` - csv_write called with empty columns
- `{"error": "rows cannot be empty"}` - csv_append called with empty rows
- `{"error": "DuckDB not installed. Install with: uv pip install duckdb"}` - Missing dependency for csv_sql
- `{"error": "Only SELECT queries are allowed for security reasons"}` - Non-SELECT SQL query attempted
- `{"error": "'INSERT' is not allowed in queries"}` - Disallowed SQL keyword used

## Dependencies

- **Built-in:** csv (Python standard library)
- **Optional:** duckdb (required only for `csv_sql` - install with `uv pip install duckdb` or `uv pip install tools[sql]`)

## Environment Variables

This tool does not require any environment variables or API keys.

## SQL Query Security

The `csv_sql` tool enforces security restrictions:
- Only `SELECT` queries are allowed
- Disallowed keywords: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `EXEC`, `EXECUTE`
- Queries run in an in-memory DuckDB database (no persistent changes)
