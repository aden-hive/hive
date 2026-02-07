# JSON Read Tool

Read and parse JSON files with optional JSONPath extraction.

## Description

Returns parsed JSON content. Use for reading config files (package.json, tsconfig.json), API responses, or any structured JSON data. Supports JSONPath for extracting specific subsets.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `file_path` | str | Yes | - | Path to the JSON file (absolute or relative) |
| `jsonpath` | str | No | `None` | Optional JSONPath expression (e.g. `$.users[*].name`, `$.dependencies`) |
| `max_content_length` | int | No | `1000000` | Max file size in bytes (1KB-10MB) |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `JSON file not found: <path>` - File does not exist
- `Not a file: <path>` - Path points to a directory
- `Not a JSON file (expected .json): <path>` - Wrong file extension
- `File too large: <size> bytes` - Exceeds max_content_length
- `Invalid JSON: <details>` - Malformed JSON syntax
- `Invalid JSONPath '<expr>': <details>` - Malformed JSONPath expression
- `Permission denied: <path>` - No read access to file

## JSONPath Examples

- `$` - Entire document
- `$.dependencies` - Field "dependencies"
- `$.users[*].name` - All "name" values from users array
- `$..email` - All email fields recursively
