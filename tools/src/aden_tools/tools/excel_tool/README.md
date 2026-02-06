# Excel Tool

Read and query Excel (.xlsx/.xls) files using DuckDB.

## Description

Provides tools to read, inspect, and query Excel files within a sandboxed session environment. Uses DuckDB's built-in `excel` extension for fast, reliable parsing with automatic type inference. Supports multi-sheet workbooks.

## Tools

### `excel_read`

Read an Excel file and return its contents with pagination support.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | Path to the Excel file (relative to session sandbox) |
| `workspace_id` | str | Yes | - | Workspace identifier |
| `agent_id` | str | Yes | - | Agent identifier |
| `session_id` | str | Yes | - | Session identifier |
| `sheet` | str | No | `None` | Sheet name to read (None = first sheet) |
| `limit` | int | No | `None` | Maximum number of rows to return (None = all rows) |
| `offset` | int | No | `0` | Number of rows to skip from the beginning |

### `excel_info`

Get metadata about an Excel file without reading all data.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | Path to the Excel file (relative to session sandbox) |
| `workspace_id` | str | Yes | - | Workspace identifier |
| `agent_id` | str | Yes | - | Agent identifier |
| `session_id` | str | Yes | - | Session identifier |

### `excel_sql`

Query an Excel sheet using SQL (powered by DuckDB). The sheet is loaded as a table named `data`.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | Path to the Excel file (relative to session sandbox) |
| `workspace_id` | str | Yes | - | Workspace identifier |
| `agent_id` | str | Yes | - | Agent identifier |
| `session_id` | str | Yes | - | Session identifier |
| `query` | str | Yes | - | SQL query to execute. The sheet is available as table `data`. |
| `sheet` | str | No | `None` | Sheet name to query (None = first sheet) |

## Environment Variables

This tool does not require any environment variables.

Requires DuckDB to be installed (`uv pip install duckdb` or `uv pip install tools[sql]`).

## Error Handling

Returns error dicts for common issues:
- `File not found: <path>` - File does not exist
- `File must have .xlsx or .xls extension` - Wrong file extension
- `DuckDB not installed. Install with: ...` - DuckDB dependency missing
- `Only SELECT queries are allowed for security reasons` - Non-SELECT query attempted
- `'<keyword>' is not allowed in queries` - Dangerous SQL keyword detected
- `offset and limit must be non-negative` - Invalid pagination parameters

## Notes

- Only SELECT queries are allowed in `excel_sql` for security
- All file paths are resolved within the session sandbox via `get_secure_path()`
- DuckDB's excel extension provides automatic type inference (integers, floats, dates, strings)
- The excel extension is a DuckDB core extension and does not require additional Python packages
- Multi-sheet workbooks are fully supported; use `excel_info` to discover available sheets
