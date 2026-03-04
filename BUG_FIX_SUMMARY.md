# Bug Fix Summary: AgentRunner.load() Error Handling

## Issue
`AgentRunner.load()` did not properly handle file read errors when loading agents from `agent.json`. When `agent.json` was empty or was a directory instead of a file, the commands would fail with raw tracebacks instead of clear error messages.

## Root Cause
In [core/framework/runner/runner.py](core/framework/runner/runner.py#L866-L868), the code was directly reading and parsing the file without validation:

```python
with open(agent_json_path) as f:
    graph, goal = load_agent_export(f.read())
```

This caused:
- **Empty files**: `json.decoder.JSONDecodeError: Expecting value: line 2 column 1 (char 1)`
- **Directory instead of file**: `IsADirectoryError: [Errno 21] Is a directory: 'exports/weird_agent/agent.json'`

## Solution

### 1. Enhanced `AgentRunner.load()` in [core/framework/runner/runner.py](core/framework/runner/runner.py)

Added comprehensive validation before JSON parsing:

```python
# Validate that agent.json is a file, not a directory
if agent_json_path.is_dir():
    raise ValueError(f"Error: agent.json is not a file (it's a directory at {agent_json_path})")

# Read and validate file content
try:
    with open(agent_json_path) as f:
        content = f.read()
except IsADirectoryError:
    raise ValueError(f"Error: agent.json is not a file (it's a directory at {agent_json_path})")
except (IOError, OSError) as e:
    raise ValueError(f"Error: Failed to read agent.json: {e}")

if not content.strip():
    raise ValueError("Error: agent.json is empty")

# Parse JSON with proper error handling
try:
    graph, goal = load_agent_export(content)
except json.JSONDecodeError as e:
    raise ValueError(f"Error: agent.json is not valid JSON: {e}")
```

**Error messages now produced:**
- Empty file: `Error: agent.json is empty`
- Directory instead of file: `Error: agent.json is not a file (it's a directory at ...)`
- Invalid JSON: `Error: agent.json is not valid JSON: ...`
- Other file read errors: `Error: Failed to read agent.json: ...`

### 2. Updated CLI Error Handlers

Modified exception handling in [core/framework/runner/cli.py](core/framework/runner/cli.py):

- **`cmd_info`** (line 731): Now catches `ValueError` in addition to `FileNotFoundError`
- **`cmd_validate`** (line 798): Now catches `ValueError` in addition to `FileNotFoundError`

This ensures clear error messages are displayed to users instead of raw tracebacks.

## Testing

Created comprehensive test file: [core/tests/test_agent_runner_load_error_handling.py](core/tests/test_agent_runner_load_error_handling.py)

Tests cover:
- Empty file handling
- Whitespace-only file handling
- agent.json being a directory
- Invalid JSON in agent.json
- Missing both agent.py and agent.json

## Affected Commands

The following `hive` commands now show proper error messages:
- `hive validate <agent_path>`
- `hive info <agent_path>`
- `hive run <agent_path>`
- `hive list`

All commands now exit cleanly with exit code 1 and clear error messages instead of showing raw tracebacks.

## Files Modified

1. **[core/framework/runner/runner.py](core/framework/runner/runner.py#L868-L890)** - Added validation and error handling in `AgentRunner.load()`
2. **[core/framework/runner/cli.py](core/framework/runner/cli.py)** - Updated `cmd_info` and `cmd_validate` to catch `ValueError`
3. **[core/tests/test_agent_runner_load_error_handling.py](core/tests/test_agent_runner_load_error_handling.py)** - Added test suite for error handling
