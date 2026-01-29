# Execute Command Tool

Executes shell commands within the secure session sandbox.

## Description

The `execute_command_tool` runs **allowlisted** commands in a sandboxed environment. By default it uses **argv execution** (no shell): no pipes, redirects, or shell operators. Commands have a 60-second timeout; stdout and stderr are captured.

## Use Cases

- Running linters or formatters (ruff, black, mypy, flake8, pytest)
- Build/docs (make)
- Listing files (ls), inspecting output (cat, head, tail, wc, echo, pwd)
- Dev tasks (python, pip)

## Usage

```python
execute_command_tool(
    command="ruff check .",
    workspace_id="workspace-123",
    agent_id="agent-456",
    session_id="session-789",
    cwd="project"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `command` | str | Yes | - | The command to execute (single command, no shell operators) |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `cwd` | str | No | `None` | Working directory (relative to session root); defaults to session root |

## Returns

**Success:**
```python
{
    "success": True,
    "command": "ruff check .",
    "return_code": 0,
    "stdout": "...",
    "stderr": "",
    "cwd": "project"
}
```

**Validation error (disallowed command, shell operators, etc.):**
```python
{
    "error": "Command 'rm' is not allowed",
    "allowed_commands": ["black", "cat", "echo", ...]
}
```

**Timeout:**
```python
{
    "error": "Command timed out after 60 seconds"
}
```

**Execution error:**
```python
{
    "error": "Failed to execute command: [message]"
}
```

## Security

- **Safe mode (default):** Commands run via `subprocess.run(args, ...)` with **no shell**. Shell operators (`|`, `;`, `&&`, `||`, `$()`, `` ` ``, `>`, `<`) are forbidden. Only allowlisted commands run (e.g. `ls`, `pwd`, `cat`, `echo`, `wc`, `head`, `tail`, `python`, `python3`, `pip`, `pytest`, `ruff`, `black`, `mypy`, `flake8`, `make`).
- **Unsafe mode:** Set `HIVE_ENABLE_UNSAFE_COMMANDS=true` to allow arbitrary shell execution (`shell=True`). Use only in trusted environments. A warning is logged when used.

## Error Handling

- Returns an error dict if the command times out (60 s), uses forbidden operators, is empty, or uses a disallowed command.
- Returns success with non-zero `return_code` if the command runs but exits with an error.
- Working directory is validated via `get_secure_path` and must stay inside the session sandbox.

## Examples

### Linting
```python
result = execute_command_tool(
    command="ruff check .",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    cwd="src"
)
```

### Tests
```python
result = execute_command_tool(
    command="pytest -v",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1"
)
```

### List files
```python
result = execute_command_tool(
    command="ls .",
    workspace_id="ws-1",
    agent_id="agent-1",
    session_id="session-1",
    cwd="repo"
)
```

## Notes

- 60-second timeout for all commands.
- Safe mode: argv execution only; no pipes, redirects, or chaining.
- Both stdout and stderr are captured.
- Working directory is created if it doesn’t exist.
