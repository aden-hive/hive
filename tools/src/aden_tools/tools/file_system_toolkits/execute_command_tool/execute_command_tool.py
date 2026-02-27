import os
import shlex
import subprocess

from mcp.server.fastmcp import FastMCP

from ..security import WORKSPACES_DIR, get_secure_path

# Allowlist of commands permitted in the sandbox.
ALLOWED_COMMANDS = frozenset({
    "python", "python3", "pip", "uv",
    "pytest", "ruff", "mypy", "black", "isort", "flake8",
    "node", "npm", "npx", "tsc",
    "cat", "head", "tail", "ls", "find", "grep", "wc",
    "echo", "diff", "sort", "uniq", "sed", "awk", "cut", "tr",
    "make",
})

# Explicitly blocked commands / patterns.
BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "mv", "cp",  # Destructive file ops require explicit tools
    "curl", "wget", "nc", "ncat", "ssh", "scp", "rsync",  # Network access
    "chmod", "chown", "chgrp",  # Permission changes
    "kill", "pkill", "killall",  # Process control
    "sudo", "su", "doas",  # Privilege escalation
    "dd", "mkfs", "mount", "umount",  # System-level ops
    "shutdown", "reboot", "poweroff", "halt",
})


def _validate_sandbox_command(command: str) -> str | None:
    """Validate command for sandbox execution.

    Returns None if allowed, or an error message string.
    """
    stripped = command.strip()
    if not stripped:
        return "Empty command."

    try:
        tokens = shlex.split(stripped)
    except ValueError:
        return "Command contains invalid shell syntax."

    base_cmd = os.path.basename(tokens[0]) if tokens else ""

    if base_cmd in BLOCKED_COMMANDS:
        return f"Command '{base_cmd}' is blocked in the sandbox."

    if base_cmd not in ALLOWED_COMMANDS:
        return (
            f"Command '{base_cmd}' is not allowed in the sandbox. "
            f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    return None


def register_tools(mcp: FastMCP) -> None:
    """Register command execution tools with the MCP server."""

    @mcp.tool()
    def execute_command_tool(
        command: str, workspace_id: str, agent_id: str, session_id: str, cwd: str | None = None
    ) -> dict:
        """
        Purpose
            Execute a shell command within the session sandbox.

        When to use
            Run validators or linters
            Generate derived artifacts (indexes, summaries)
            Perform controlled maintenance tasks

        Rules & Constraints
            Commands are validated against an allowlist before execution.
            No network access — network tools are blocked.
            No destructive commands — rm, mv, cp are blocked; use dedicated file tools.
            Shell operators (;, &&, ||, |) are not supported.

        Args:
            command: The shell command to execute
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            cwd: The working directory for the command (relative to session root, optional)

        Returns:
            Dict with command output and execution details, or error dict
        """
        try:
            # Validate command against allowlist
            error = _validate_sandbox_command(command)
            if error:
                return {"error": f"Command rejected: {error}"}

            # Parse command into args list — never use shell=True
            args = shlex.split(command)

            # Default cwd is the session root
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
            os.makedirs(session_root, exist_ok=True)

            if cwd:
                secure_cwd = get_secure_path(cwd, workspace_id, agent_id, session_id)
            else:
                secure_cwd = session_root

            result = subprocess.run(
                args, shell=False, cwd=secure_cwd, capture_output=True, text=True, timeout=60
            )

            return {
                "success": True,
                "command": command,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "cwd": cwd or ".",
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 60 seconds"}
        except Exception as e:
            return {"error": f"Failed to execute command: {str(e)}"}
