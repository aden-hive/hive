# View File Tool

Reads the content of a file within the secure session sandbox.

## Description

The `view_file` tool allows you to read and retrieve the complete content of files within a sandboxed session environment. It provides metadata about the file along with its content.

## Use Cases

- Reading configuration files
- Viewing source code
- Inspecting log files
- Retrieving data files for processing

## Usage

```python
view_file(
    path="config/settings.json",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to the file (relative to session root) |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `encoding` | str | No | `"utf-8"` | The encoding to use for reading the file |
| `max_size` | int | No | `10485760` | Maximum size of file content to return in bytes (10 MB) |
| `hashline` | bool | No | `False` | If True, return content with `N:hhhh\|content` anchors for use with `hashline_edit` |
| `offset` | int | No | `1` | 1-indexed start line (only used when `hashline=True`) |
| `limit` | int | No | `0` | Max lines to return, 0 = all (only used when `hashline=True`) |

## Returns

Returns a dictionary with the following structure:

**Success (default mode):**
```python
{
    "success": True,
    "path": "config/settings.json",
    "content": "{\"debug\": true}",
    "size_bytes": 16,
    "lines": 1
}
```

**Success (hashline mode):**
```python
{
    "success": True,
    "path": "app.py",
    "content": "1:a3f2|def main():\n2:f1c4|    print(\"hello\")",
    "hashline": True,
    "offset": 1,
    "limit": 0,
    "total_lines": 2,
    "shown_lines": 2,
    "size_bytes": 35
}
```

**Error:**
```python
{
    "error": "File not found at config/settings.json"
}
```

## Error Handling

- Returns an error dict if the file doesn't exist
- Returns an error dict if the file cannot be read (permission issues, encoding errors, etc.)
- Handles binary files gracefully by returning appropriate error messages

## Examples

### Reading a text file
```python
result = view_file(
    path="README.md",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": "README.md", "content": "# My Project\n...", "size_bytes": 1024, "lines": 42}
```

### Handling missing files
```python
result = view_file(
    path="nonexistent.txt",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"error": "File not found at nonexistent.txt"}
```
