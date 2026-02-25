# CSV Tool

The CSV tool provides a suite of capabilities for working with CSV files within the Aden Hive environment. It supports basic CRUD operations and advanced SQL querying for efficient data analysis.

## Features

- **Read & Write**: Easily read from and write to CSV files with proper encoding and header management.
- **Pagination**: Read large CSV files in chunks using `limit` and `offset`.
- **Append**: Efficiently add new data rows to existing files while maintaining column consistency.
- **Metadata**: Inspect CSV structure (column names, row counts, file size) without loading the entire file.
- **SQL Querying**: Use standard SQL syntax to filter, aggregate, and sort CSV data, powered by DuckDB.

## Tools

### `csv_read`
Reads a CSV file and returns its contents as a list of dictionaries.
- **path**: Relative path to the file.
- **limit**: Maximum rows to return.
- **offset**: Rows to skip.

### `csv_write`
Creates a new CSV file with the specified columns and data.
- **path**: Relative path to the file.
- **columns**: List of header names.
- **rows**: List of data dictionaries.

### `csv_append`
Appends new rows to an existing CSV file.
- **path**: Relative path to the file.
- **rows**: List of data dictionaries (keys must match existing headers).

### `csv_info`
Retrieves file metadata without reading the data.
- **path**: Relative path to the file.

### `csv_sql`
Executes an SQL `SELECT` query against a CSV file. The CSV is automatically mapped to a table named `data`.
- **path**: Relative path to the file.
- **query**: SQL `SELECT` statement (e.g., `SELECT * FROM data WHERE status = 'active'`).
- *Note: Requires `duckdb` installed (`uv pip install duckdb`).*

## Security

All file operations use `get_secure_path` to ensure they stay within the session's sandbox. The `csv_sql` tool only permits `SELECT` statements to prevent unauthorized data modification or schema changes.
