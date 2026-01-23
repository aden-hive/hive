# Replace File Content Tool

Replaces specific string occurrences in a file within the secure session sandbox.

## Description

The `replace_file_content` tool performs find-and-replace operations on file content. It replaces all occurrences of a target string with a replacement string, providing details about the number of replacements made.

## Use Cases

- Updating configuration values
- Refactoring code (renaming variables, functions)
- Batch text replacements
- Updating version numbers or URLs

## Usage

```python
replace_file_content(
    path="config/settings.json",
    target='"debug": false',
    replacement='"debug": true',
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to the file (relative to session root) |
| `target` | str | Yes | - | The string to search for and replace |
| `replacement` | str | Yes | - | The string to replace it with |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |

## Returns

Returns a dictionary with the following structure:

**Success:**
```python
{
    "success": True,
    "path": "config/settings.json",
    "occurrences_replaced": 3,
    "target_length": 15,
    "replacement_length": 14
}
```

**Error:**
```python
{
    "error": "Target string not found in config/settings.json"
}
```

## Error Handling

- Returns an error dict if the file doesn't exist
- Returns an error dict if the target string is not found in the file
- Returns an error dict if the file cannot be read or written
- All occurrences of the target string are replaced

## Examples

### Replacing a configuration value
```python
result = replace_file_content(
    path="app.config",
    target="localhost",
    replacement="production.example.com",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": "app.config", "occurrences_replaced": 2, "target_length": 9, "replacement_length": 23}
```

### Handling missing target string
```python
result = replace_file_content(
    path="README.md",
    target="nonexistent text",
    replacement="new text",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"error": "Target string not found in README.md"}
```

## Notes

- This operation replaces **all** occurrences of the target string
- The replacement is case-sensitive
- For regex-based replacements, consider using a different tool
- The file is overwritten with the new content
