# Excel Tool

Read and write Excel (.xlsx) files using pandas.

## Description

Provides comprehensive Excel file manipulation capabilities for agents, including reading, writing, appending data, and inspecting file metadata. Uses `pandas` for robust DataFrame-based operations with `openpyxl` as the Excel engine for maximum compatibility.

## Tools

### excel_read

Read data from an Excel file with pagination support.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| path | string | Yes | Path to the Excel file |
| workspace_id | string | Yes | Workspace identifier |
| agent_id | string | Yes | Agent identifier |
| session_id | string | Yes | Session identifier |
| sheet_name | string/int | No | Sheet name or index (default: first sheet) |
| limit | int | No | Maximum rows to return |
| offset | int | No | Rows to skip (default: 0) |
| include_empty_rows | bool | No | Include empty rows (default: false) |

### excel_write

Create a new Excel file with specified data.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| path | string | Yes | Path for the new Excel file |
| workspace_id | string | Yes | Workspace identifier |
| agent_id | string | Yes | Agent identifier |
| session_id | string | Yes | Session identifier |
| columns | list[str] | Yes | Column names for header row |
| rows | list[dict] | Yes | Data rows as dictionaries |
| sheet_name | string | No | Sheet name (default: "Sheet1") |

### excel_append

Append rows to an existing Excel file.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| path | string | Yes | Path to existing Excel file |
| workspace_id | string | Yes | Workspace identifier |
| agent_id | string | Yes | Agent identifier |
| session_id | string | Yes | Session identifier |
| rows | list[dict] | Yes | Rows to append |
| sheet_name | string | No | Sheet to append to (default: first) |

### excel_info

Get metadata about an Excel file without reading all data.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| path | string | Yes | Path to the Excel file |
| workspace_id | string | Yes | Workspace identifier |
| agent_id | string | Yes | Agent identifier |
| session_id | string | Yes | Session identifier |

### excel_list_sheets

List all sheet names in an Excel file.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| path | string | Yes | Path to the Excel file |
| workspace_id | string | Yes | Workspace identifier |
| agent_id | string | Yes | Agent identifier |
| session_id | string | Yes | Session identifier |

## Installation

The Excel tools require `openpyxl` as Pandas Excel engine:

```bash
# Install as optional dependency
pip install aden-tools[excel]

# Or install openpyxl directly
pip install openpyxl
```

## Error Handling

All tools return error dictionaries on failure:

| Error Case | Response |
|------------|----------|
| File not found | `{"error": "File not found: path"}` |
| Invalid extension | `{"error": "File must have an Excel extension..."}` |
| Sheet not found | `{"error": "Sheet 'name' not found..."}` |
| openpyxl missing | `{"error": "openpyxl not installed..."}` |
| Empty columns | `{"error": "columns cannot be empty"}` |
| Empty rows (append) | `{"error": "rows cannot be empty"}` |

## Example Usage

### Reading Excel Data

```python
# Read first 10 rows from default sheet
result = excel_read(
    path="data.xlsx",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="sess-789",
    limit=10
)

# Read specific sheet
result = excel_read(
    path="report.xlsx",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="sess-789",
    sheet_name="Sales Data"
)
```

### Writing Excel Data

```python
result = excel_write(
    path="output.xlsx",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="sess-789",
    columns=["Name", "Age", "City"],
    rows=[
        {"Name": "Alice", "Age": 30, "City": "NYC"},
        {"Name": "Bob", "Age": 25, "City": "LA"}
    ],
    sheet_name="Employees"
)
```

### Appending Data

```python
result = excel_append(
    path="log.xlsx",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="sess-789",
    rows=[{"Date": "2024-01-15", "Event": "Login"}]
)
```

### Getting File Info

```python
result = excel_info(
    path="report.xlsx",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="sess-789"
)
# Returns: sheet_count, sheet_names, sheets (with columns/row counts), file_size_bytes
```

## Notes

- Uses pandas with openpyxl engine for reliable .xlsx support
- Datetime values are serialized to ISO 8601 format
- NaN values are converted to None (null in JSON)
- First row is always treated as headers
- Multi-sheet files are fully supported
