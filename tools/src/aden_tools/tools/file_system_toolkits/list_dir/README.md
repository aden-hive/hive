# List Dir Tool

Lists the contents of a directory within the secure session sandbox.

## Description

The `list_dir` tool allows you to explore directory contents, viewing all files and subdirectories with their metadata. It provides a structured view of the filesystem hierarchy.

## Use Cases

- Exploring project structure
- Finding specific files
- Checking for file existence
- Understanding directory organization

## Usage

```python
list_dir(
    path="src",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The directory path (relative to session root) |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |

## Returns

Returns a dictionary with the following structure:

**Success:**
```python
{
    "success": True,
    "path": "src",
    "entries": [
        {"name": "main.py", "type": "file", "size_bytes": 1024},
        {"name": "utils", "type": "directory", "size_bytes": null}
    ],
    "total_count": 2
}
```

**Error:**
```python
{
    "error": "Directory not found at src"
}
```

## Error Handling

- Returns an error dict if the directory doesn't exist
- Returns an error dict if the path points to a file instead of a directory
- Returns an error dict if the directory cannot be read (permission issues, etc.)

## Examples

### Listing directory contents
```python
result = list_dir(
    path=".",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": ".", "entries": [...], "total_count": 5}
```

### Checking an empty directory
```python
result = list_dir(
    path="empty_folder",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": "empty_folder", "entries": [], "total_count": 0}
```
