# Execute Command Tool

Executes shell commands within the secure session sandbox.

## Description

The `execute_command_tool` allows you to run arbitrary shell commands in a sandboxed environment. Commands are executed with a 60-second timeout and capture both stdout and stderr output.

## Use Cases

- Running build commands (npm build, make, etc.)
- Executing tests
- Running linters or formatters
- Performing git operations
- Installing dependencies

## Usage

```python
execute_command_tool(
    command="npm install",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789",
    cwd="project"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `command` | str | Yes | - | The shell command to execute |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `cwd` | str | No | "." | The working directory for the command (relative to session root) |

## Returns

Returns a dictionary with the following structure:

**Success:**
```python
{
    "success": True,
    "command": "npm install",
    "return_code": 0,
    "stdout": "added 42 packages in 3s",
    "stderr": "",
    "cwd": "project"
}
```

**Command failure (non-zero exit):**
```python
{
    "success": True,  # Command executed successfully, but exited with error code
    "command": "npm test",
    "return_code": 1,
    "stdout": "",
    "stderr": "Error: Tests failed",
    "cwd": "."
}
```

**Timeout:**
```python
{
    "error": "Command timed out after 60 seconds"
}
```

**Error:**
```python
{
    "error": "Failed to execute command: [error message]"
}
```

## Error Handling

- Returns an error dict if the command times out (60 second limit)
- Returns an error dict if the command cannot be executed
- Returns success with non-zero return_code if command runs but fails
- Commands are executed in a sandboxed session environment
- Working directory defaults to session root if not specified

## Security Considerations

- Commands are executed within the session sandbox only
- File access is restricted to the session directory
- Network access depends on sandbox configuration
- Commands run with the permissions of the session user
- Use with caution as shell injection is possible

## Examples

### Running a build command
```python
result = execute_command_tool(
    command="npm run build",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    cwd="frontend"
)
# Returns: {"success": True, "return_code": 0, "stdout": "Build complete", ...}
```

### Running tests with output
```python
result = execute_command_tool(
    command="pytest -v",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "return_code": 0, "stdout": "test output...", "stderr": ""}
```

### Handling command failures
```python
result = execute_command_tool(
    command="nonexistent-command",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
# Returns: {"success": True, "return_code": 127, "stderr": "command not found", ...}
```

### Running git commands
```python
result = execute_command_tool(
    command="git status",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    cwd="repo"
)
# Returns: {"success": True, "return_code": 0, "stdout": "On branch main...", ...}
```

## Notes

- 60-second timeout for all commands
- Commands are executed using shell=True (supports pipes, redirects, etc.)
- Both stdout and stderr are captured separately
- Return code 0 typically indicates success
- Working directory is created if it doesn't exist
- Command output is returned as text (UTF-8 encoding)
