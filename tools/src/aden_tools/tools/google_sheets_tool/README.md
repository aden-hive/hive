# Google Sheets Tool

Integration tool for reading, writing, and managing Google Sheets via the Google Sheets API v4.

## Features

- **Spreadsheet Management**: Create spreadsheets, get metadata
- **Read Data**: Get values from ranges with different rendering options
- **Write Data**: Update cells, append rows, batch updates
- **Clear Data**: Clear ranges, batch clear operations
- **Sheet Management**: Add and delete sheets/tabs within spreadsheets

## Authentication

This tool supports two authentication methods:

1. **Credential Store** (recommended):
   - Configure `google` credential via the Aden credential store
   - Requires `https://www.googleapis.com/auth/spreadsheets` scope

2. **Environment Variable**:
   - Set `GOOGLE_ACCESS_TOKEN` with a valid OAuth2 access token
   - Useful for local development and testing

## Available Tools

### Spreadsheet Management

- `google_sheets_get_spreadsheet` - Get spreadsheet metadata and properties
- `google_sheets_create_spreadsheet` - Create a new spreadsheet with optional sheets

### Reading Data

- `google_sheets_get_values` - Get values from a range (A1 notation)

### Writing Data

- `google_sheets_update_values` - Update values in a specific range
- `google_sheets_append_values` - Append rows to a sheet
- `google_sheets_clear_values` - Clear values in a range

### Batch Operations

- `google_sheets_batch_update_values` - Update multiple ranges in one request
- `google_sheets_batch_clear_values` - Clear multiple ranges in one request

### Sheet Management

- `google_sheets_add_sheet` - Add a new sheet/tab to a spreadsheet
- `google_sheets_delete_sheet` - Delete a sheet/tab from a spreadsheet

## Usage Examples

### Read data from a spreadsheet

```python
# Get values from a range
result = google_sheets_get_values(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    range_name="Sheet1!A1:D10"
)
# Returns: {"range": "Sheet1!A1:D10", "values": [["A1", "B1", ...], ...]}
```

### Write data to a spreadsheet

```python
# Update a range
result = google_sheets_update_values(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    range_name="Sheet1!A1:B2",
    values=[
        ["Name", "Email"],
        ["John Doe", "john@example.com"]
    ]
)
```

### Append rows

```python
# Append new rows
result = google_sheets_append_values(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    range_name="Sheet1!A1",
    values=[
        ["Jane Smith", "jane@example.com"],
        ["Bob Johnson", "bob@example.com"]
    ]
)
```

### Create a new spreadsheet

```python
# Create spreadsheet with multiple sheets
result = google_sheets_create_spreadsheet(
    title="My New Spreadsheet",
    sheet_titles=["Data", "Analysis", "Summary"]
)
# Returns: {"spreadsheetId": "...", "spreadsheetUrl": "..."}
```

### Batch operations

```python
# Update multiple ranges at once
result = google_sheets_batch_update_values(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    data=[
        {"range": "Sheet1!A1:B1", "values": [["Header 1", "Header 2"]]},
        {"range": "Sheet1!A2:B3", "values": [["Data 1", "Data 2"], ["Data 3", "Data 4"]]}
    ]
)
```

### Manage sheets

```python
# Add a new sheet
result = google_sheets_add_sheet(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    title="New Sheet",
    row_count=1000,
    column_count=26
)

# Delete a sheet (need sheet_id from metadata)
result = google_sheets_delete_sheet(
    spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
    sheet_id=123456
)
```

## A1 Notation

Google Sheets uses A1 notation to reference cells and ranges:

- Single cell: `Sheet1!A1`
- Range: `Sheet1!A1:D10`
- Entire column: `Sheet1!A:A`
- Entire row: `Sheet1!1:1`
- Multiple sheets: Use sheet name prefix

## Value Input Options

When writing data, you can specify how values should be interpreted:

- `USER_ENTERED` (default): Parse values as if typed by a user (formulas, numbers, dates)
- `RAW`: Store values as-is without parsing

## Value Render Options

When reading data, you can specify how values should be rendered:

- `FORMATTED_VALUE` (default): Values as they appear in the UI
- `UNFORMATTED_VALUE`: Unformatted values (numbers as numbers)
- `FORMULA`: Cell formulas

## Error Handling

All tools return error information in the response:

```python
{
    "error": "Error message",
    "help": "Suggestion for fixing the error"  # When applicable
}
```

Common errors:
- `401`: Invalid or expired access token
- `403`: Insufficient permissions (check scopes)
- `404`: Spreadsheet or range not found
- `429`: Rate limit exceeded

## API Reference

- [Google Sheets API v4 Documentation](https://developers.google.com/sheets/api/reference/rest)
- [A1 Notation Guide](https://developers.google.com/sheets/api/guides/concepts#cell)
- [OAuth2 Scopes](https://developers.google.com/sheets/api/guides/authorizing)
