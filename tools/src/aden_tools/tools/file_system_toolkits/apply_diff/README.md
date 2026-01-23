# Apply Diff Tool

Applies a unified diff patch to a file within the secure session sandbox.

## Description

The `apply_diff` tool applies structured diff patches to files, enabling precise modifications using the diff-match-patch algorithm. It can apply multiple patches in a single operation and reports success status for each patch.

## Use Cases

- Applying code review suggestions
- Implementing automated refactoring
- Synchronizing file changes from version control
- Making precise, contextual file modifications

## Usage

```python
apply_diff(
    path="src/main.py",
    diff_text="@@ -1,3 +1,3 @@\n import os\n-import sys\n+import json\n from typing import List",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to the file (relative to session root) |
| `diff_text` | str | Yes | - | The diff patch text to apply |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |

## Returns

Returns a dictionary with the following structure:

**Success (all patches applied):**
```python
{
    "success": True,
    "path": "src/main.py",
    "patches_applied": 3,
    "all_successful": True
}
```

**Partial success (some patches failed):**
```python
{
    "success": False,
    "path": "src/main.py",
    "patches_applied": 2,
    "patches_failed": 1,
    "error": "Failed to apply 1 of 3 patches"
}
```

**Error:**
```python
{
    "error": "File not found at src/main.py"
}
```

## Error Handling

- Returns an error dict if the file doesn't exist
- Returns partial success if some patches fail to apply
- Returns an error dict if the diff text is malformed
- Uses diff-match-patch library for intelligent fuzzy matching

## Examples

### Applying a single-line change
```python
diff = "@@ -10,1 +10,1 @@\n-    old_code()\n+    new_code()"
result = apply_diff(
    path="module.py",
    diff_text=diff,
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "path": "module.py", "patches_applied": 1, "all_successful": True}
```

### Handling patch failures
```python
result = apply_diff(
    path="outdated.py",
    diff_text="@@ -1,1 +1,1 @@\n-nonexistent line\n+new line",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": False, "path": "outdated.py", "patches_applied": 0, "patches_failed": 1, ...}
```

## Notes

- Uses the diff-match-patch library for patch application
- Supports fuzzy matching for more robust patching
- Patches are applied atomically (all or nothing for file write)
- The file is only modified if at least one patch succeeds
