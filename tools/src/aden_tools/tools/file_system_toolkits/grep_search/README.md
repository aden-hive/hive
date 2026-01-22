# Grep Search Tool

Searches for regex patterns in files or directories within the secure session sandbox.

## Description

The `grep_search` tool provides powerful pattern matching capabilities across files and directories. It uses Python's regex engine to find matches and returns detailed results including file paths, line numbers, and matched content.

## Use Cases

- Finding function or variable definitions
- Searching for TODO comments or specific patterns
- Analyzing code for security issues or patterns
- Locating configuration values across multiple files

## Usage

```python
grep_search(
    path="src",
    pattern="def \\w+\\(",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789",
    recursive=True
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to search in (file or directory, relative to session root) |
| `pattern` | str | Yes | - | The regex pattern to search for |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `recursive` | bool | No | False | Whether to search recursively in subdirectories |

## Returns

Returns a dictionary with the following structure:

**Success:**
```python
{
    "success": True,
    "pattern": "def \\w+\\(",
    "path": "src",
    "recursive": True,
    "matches": [
        {
            "file": "src/main.py",
            "line_number": 10,
            "line_content": "def process_data(args):"
        },
        {
            "file": "src/utils.py",
            "line_number": 5,
            "line_content": "def helper_function():"
        }
    ],
    "total_matches": 2
}
```

**No matches:**
```python
{
    "success": True,
    "pattern": "nonexistent",
    "path": "src",
    "recursive": False,
    "matches": [],
    "total_matches": 0
}
```

**Error:**
```python
{
    "error": "Failed to perform grep search: [error message]"
}
```

## Error Handling

- Returns an error dict if the path doesn't exist
- Skips files that cannot be decoded (binary files, encoding errors)
- Skips files with permission errors
- Returns empty matches list if no matches found
- Handles invalid regex patterns with error message

## Examples

### Searching for function definitions
```python
result = grep_search(
    path="src",
    pattern="^def ",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    recursive=True
)
# Returns: {"success": True, "pattern": "^def ", "matches": [...], "total_matches": 15}
```

### Searching a single file
```python
result = grep_search(
    path="config.py",
    pattern="API_KEY",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "pattern": "API_KEY", "matches": [{...}], "total_matches": 1}
```

### Case-insensitive search using regex flags
```python
result = grep_search(
    path="docs",
    pattern="(?i)todo",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    recursive=True
)
# Finds "TODO", "todo", "Todo", etc.
```

## Notes

- Uses Python's `re` module for regex matching
- Binary files and files with encoding errors are automatically skipped
- Line numbers start at 1
- Returned file paths are relative to the session root
- For non-recursive directory searches, only files in the immediate directory are searched
