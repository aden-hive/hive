# File Write Tool

Write content to local files with encoding support.

## Description

Can create new files or overwrite/append to existing ones. Use for saving data, creating configs, writing reports, or exporting results. Optionally creates parent directories if they don't exist.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `file_path` | str | Yes | - | Path to the file to write (absolute or relative) |
| `content` | str | Yes | - | Content to write to the file |
| `encoding` | str | No | `utf-8` | File encoding (utf-8, latin-1, etc.) |
| `mode` | str | No | `write` | Write mode - 'write' (overwrite) or 'append' |
| `create_dirs` | bool | No | `True` | Create parent directories if they don't exist |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `Parent directory does not exist: <path>` - Parent dir missing and create_dirs=False
- `Invalid mode: <mode>. Use 'write' or 'append'.` - Invalid mode specified
- `Permission denied: <path>` - No write access to file/directory
- `OS error writing file: <error>` - Filesystem error
