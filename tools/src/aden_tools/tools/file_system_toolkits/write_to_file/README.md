# Write to File Tool

Writes content to a file within the secure session sandbox. Supports both overwriting and appending modes.

## Description

The `write_to_file` tool allows you to create new files or modify existing files within a sandboxed session environment. It automatically creates parent directories if they don't exist and provides flexible write modes.

## Use Cases

- Creating new configuration files
- Writing generated code or data
- Appending logs or output to existing files
- Saving processed results to disk

## Usage

```python
write_to_file(
    path="config/settings.json",
    content='{"debug": true}',
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789",
    append=False
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to the file (relative to session root) |
| `content` | str | Yes | - | The content to write to the file |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `append` | bool | No | False | Whether to append to the file instead of overwriting |

## Returns

Returns a dictionary with the following structure:

**Success:**
```python
{
    "success": True,
    "path": "config/settings.json",
    "mode": "written",  # or "appended"
    "bytes_written": 18
}
```

**Error:**
```python
{
    "error": "Failed to write to file: [error message]"
}
```

## Error Handling

- Returns an error dict if the file cannot be written (permission issues, invalid path, etc.)
- Automatically creates parent directories if they don't exist
- Handles encoding errors gracefully

## Examples

### Creating a new file
```python
result = write_to_file(
    path="data/output.txt",
    content="Hello, world!",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": "data/output.txt", "mode": "written", "bytes_written": 13}
```

### Appending to a file
```python
result = write_to_file(
    path="logs/activity.log",
    content="\n[INFO] Task completed",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    append=True
)
# Returns: {"success": True, "path": "logs/activity.log", "mode": "appended", "bytes_written": 24}
```
