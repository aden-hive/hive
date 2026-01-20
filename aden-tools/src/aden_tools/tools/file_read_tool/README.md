# File Read Tool

Read contents of local files with encoding support.

## Description

Use for reading configs, data files, source code, logs, or any text file. Returns file content along with path, name, size, and encoding metadata.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `file_path` | str | Yes | - | Path to the file to read (absolute or relative) |
| `encoding` | str | No | `utf-8` | File encoding (utf-8, latin-1, etc.) |
| `max_size` | int | No | `10000000` | Maximum file size to read in bytes (default 10MB) |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `File not found: <path>` - File does not exist
- `Not a file: <path>` - Path points to a directory
- `File too large: <size> bytes (max: <max_size>)` - File exceeds max_size limit
- `Failed to decode file with encoding '<encoding>'` - Wrong encoding specified
- `Permission denied: <path>` - No read access to file
