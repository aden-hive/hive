# Excel Tool

Tool for reading and manipulating Excel files (.xlsx and .xls formats) within the Aden agent framework.

## Features

- **Read Excel files** with support for multiple sheets
- **Write data to Excel files** with custom sheet names
- **Append data** to existing Excel files
- **Get file information** without loading all data
- **Create new sheets** in existing Excel files
- **Support for offset and limit** parameters for large files
- **Automatic type handling** for various Excel data types

## Available Tools

### `excel_read`
Read an Excel file and return its contents.

**Parameters:**
- `path`: Path to the Excel file (relative to session sandbox)
- `workspace_id`: Workspace identifier
- `agent_id`: Agent identifier 
- `session_id`: Session identifier
- `sheet_name`: Specific sheet name to read (optional, defaults to first sheet)
- `limit`: Maximum number of rows to return (optional)
- `offset`: Number of rows to skip from the beginning (default: 0)

**Returns:**
```json
{
  "success": true,
  "path": "data.xlsx",
  "sheet": "Sheet1",
  "available_sheets": ["Sheet1", "Sheet2"],
  "columns": ["Name", "Age", "City"],
  "column_count": 3,
  "rows": [
    {"Name": "Alice", "Age": 25, "City": "New York"},
    {"Name": "Bob", "Age": 30, "City": "London"}
  ],
  "row_count": 2,
  "total_rows": 100,
  "offset": 0,
  "limit": null
}
```

### `excel_write`
Write data to a new Excel file.

**Parameters:**
- `path`: Path to the Excel file (relative to session sandbox)
- `workspace_id`: Workspace identifier
- `agent_id`: Agent identifier
- `session_id`: Session identifier
- `columns`: List of column names for the header
- `rows`: List of dictionaries, each representing a row
- `sheet_name`: Name for the Excel sheet (default: "Sheet1")

**Returns:**
```json
{
  "success": true,
  "path": "output.xlsx",
  "sheet": "Data",
  "columns": ["Product", "Price", "Stock"],
  "column_count": 3,
  "rows_written": 50
}
```

### `excel_append`
Append rows to an existing Excel file.

**Parameters:**
- `path`: Path to the Excel file (relative to session sandbox)
- `workspace_id`: Workspace identifier
- `agent_id`: Agent identifier
- `session_id`: Session identifier
- `rows`: List of dictionaries to append
- `sheet_name`: Sheet name to append to (optional, defaults to first sheet)

**Returns:**
```json
{
  "success": true,
  "path": "data.xlsx",
  "sheet": "Sheet1",
  "available_sheets": ["Sheet1"],
  "columns": ["Name", "Age", "City"],
  "rows_appended": 5,
  "total_rows": 105
}
```

### `excel_info`
Get information about an Excel file without reading all data.

**Parameters:**
- `path`: Path to the Excel file (relative to session sandbox)
- `workspace_id`: Workspace identifier
- `agent_id`: Agent identifier
- `session_id`: Session identifier

**Returns:**
```json
{
  "success": true,
  "path": "data.xlsx",
  "file_size": 1024000,
  "sheets": [
    {
      "name": "Sheet1",
      "columns": ["Name", "Age", "City"],
      "column_count": 3,
      "row_count": 100
    },
    {
      "name": "Summary",
      "columns": ["Total", "Average"],
      "column_count": 2,
      "row_count": 10
    }
  ],
  "sheet_count": 2
}
```

### `excel_create_sheet`
Add a new sheet to an existing Excel file or create file if it doesn't exist.

**Parameters:**
- `path`: Path to the Excel file (relative to session sandbox)
- `workspace_id`: Workspace identifier
- `agent_id`: Agent identifier
- `session_id`: Session identifier
- `sheet_name`: Name of the new sheet
- `columns`: List of column names for the header
- `rows`: Optional list of dictionaries for initial data

**Returns:**
```json
{
  "success": true,
  "path": "workbook.xlsx",
  "sheet": "Analysis",
  "columns": ["Metric", "Value"],
  "rows_written": 3,
  "existing_sheets": ["Sheet1", "Data"],
  "file_created": false
}
```

## File Format Support

- **Excel 2007+ (.xlsx)** - Primary support with full features
- **Excel 97-2003 (.xls)** - Basic support (automatically converted to .xlsx)

## Dependencies

- `pandas>=2.0.0` - Data manipulation and analysis
- `openpyxl>=3.1.0` - Excel file reading/writing engine

## Error Handling

All tools return consistent error responses:

```json
{
  "error": "Description of what went wrong"
}
```

Common error scenarios:
- File not found
- Invalid file extension
- Malformed Excel file
- Sheet not found
- Permission denied
- Invalid parameters (negative offset/limit)

## Usage Examples

### Reading an Excel File
```python
# Read first sheet of an Excel file
result = excel_read(
    path="sales_data.xlsx",
    workspace_id="proj_123",
    agent_id="sales_agent", 
    session_id="session_456"
)

if result["success"]:
    for row in result["rows"]:
        print(f"Product: {row['Product']}, Sales: {row['Sales']}")
```

### Reading a Specific Sheet
```python
# Read a specific sheet
result = excel_read(
    path="report.xlsx",
    sheet_name="Q4_Summary",
    workspace_id="proj_123",
    agent_id="analytics_agent",
    session_id="session_789"
)
```

### Writing Data to Excel
```python
# Create new Excel file with sales data
columns = ["Product", "Price", "Units", "Revenue"]
rows = [
    {"Product": "Laptop", "Price": 999.99, "Units": 25, "Revenue": 24999.75},
    {"Product": "Mouse", "Price": 29.99, "Units": 100, "Revenue": 2999.00}
]

result = excel_write(
    path="sales_report.xlsx",
    columns=columns,
    rows=rows,
    sheet_name="Sales_Data",
    workspace_id="proj_123",
    agent_id="reporting_agent",
    session_id="session_012"
)
```

### Appending Data
```python
# Add new sales records to existing file
new_sales = [
    {"Product": "Keyboard", "Price": 79.99, "Units": 50, "Revenue": 3999.50}
]

result = excel_append(
    path="sales_report.xlsx",
    rows=new_sales,
    workspace_id="proj_123",
    agent_id="sales_agent",
    session_id="session_345"
)
```

### Getting File Information
```python
# Check what sheets and columns are available
result = excel_info(
    path="complex_workbook.xlsx",
    workspace_id="proj_123",
    agent_id="data_agent",
    session_id="session_678"
)

if result["success"]:
    print(f"File has {result['sheet_count']} sheets:")
    for sheet in result["sheets"]:
        print(f"  - {sheet['name']}: {sheet['row_count']} rows, {sheet['column_count']} columns")
```

## Performance Considerations

- **Large files**: Use `limit` and `offset` parameters to process data in chunks
- **Memory usage**: Excel operations load data into memory; consider file size limits
- **Multiple sheets**: Use `excel_info` to understand file structure before reading
- **File format**: .xlsx files are generally more efficient than .xls for large datasets

## Security

- All file operations use the secure path validation system
- Files are restricted to the session sandbox directory
- Path traversal attacks are prevented
- File type validation enforces Excel formats only