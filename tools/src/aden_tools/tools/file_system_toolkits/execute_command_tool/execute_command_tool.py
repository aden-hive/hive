from __future__ import annotations

import os
import re
import shlex
import subprocess

from mcp.server.fastmcp import FastMCP

from ..security import WORKSPACES_DIR, get_secure_path

# Whitelist of allowed commands for security
# Commands must be in this list to be executed
ALLOWED_COMMANDS = {
    "echo",
    "ls",
    "cat",
    "grep",
    "find",
    "head",
    "tail",
    "wc",
    "sort",
    "uniq",
    "cut",
    "awk",
    "sed",
    "tr",
    "python",
    "python3",
    "node",
    "npm",
    "pytest",
    "ruff",
    "black",
    "mypy",
    "git",
    "make",
}

# Blocked shell metacharacters that enable command injection
BLOCKED_METACHARS = [
    r"[;&|`$()]",  # Command chaining, pipes, subshells, command substitution
    r"<\(|>\(|<<<",  # Process substitution
    r"\$\(",  # Command substitution $(...)
    r"`",  # Backtick command substitution
    r">>|<<",  # Heredoc
    r"&&|\|\|",  # Logical operators
]

# Blocked patterns for dangerous operations
BLOCKED_PATTERNS = [
    r"rm\s+-rf",  # Destructive deletion
    r"rm\s+-\*",  # Destructive deletion
    r"format\s+",  # Disk formatting
    r"mkfs",  # Filesystem creation
    r"dd\s+if=",  # Disk operations
    r"shutdown|reboot|halt",  # System control
    r"curl\s+.*\|.*sh",  # Download and execute
    r"wget\s+.*\|.*sh",  # Download and execute
]


def _validate_command(command: str) -> tuple[bool, str | None]:
    """
    Validate command for security.

    Returns:
        (is_valid, error_message)
    """
    if not command or not command.strip():
        return False, "Command cannot be empty"

    # Check for blocked metacharacters in the raw command string
    for pattern in BLOCKED_METACHARS:
        if re.search(pattern, command):
            return False, f"Command contains blocked shell metacharacters: {pattern}"

    # Check for redirects (>, <, >>, <<) in the raw command
    if re.search(r"[<>]", command):
        return False, "Command contains redirect operators (>, <) which are not allowed"

    # Check for blocked dangerous patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Command matches blocked dangerous pattern: {pattern}"

    # Parse command to extract executable
    try:
        # Use shlex to safely parse the command
        parts = shlex.split(command)
        if not parts:
            return False, "Command has no executable"

        executable = parts[0]

        # Check if executable is in whitelist
        # Allow full paths if they point to whitelisted executables
        if "/" in executable or "\\" in executable:
            # Extract just the basename for whitelist check
            executable = os.path.basename(executable)

        if executable not in ALLOWED_COMMANDS:
            return False, f"Command '{executable}' is not in the allowed commands whitelist"

        return True, None

    except ValueError as e:
        # shlex.split can raise ValueError for unclosed quotes
        return False, f"Invalid command syntax: {str(e)}"


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
            - Commands must be in the allowed whitelist
            - No shell metacharacters (pipes, redirects, command chaining)
            - No destructive commands (rm -rf, format, etc.)
            - Commands are executed with shell=False for security
            - Network access depends on sandbox configuration
            - Output must be treated as data, not truth

        Security
            This tool uses shell=False and command whitelisting to prevent
            command injection attacks. Shell metacharacters are blocked.

        Args:
            command: The shell command to execute (must be whitelisted, no shell metacharacters)
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            cwd: The working directory for the command (relative to session root, optional)

        Returns:
            Dict with command output and execution details, or error dict
        """
        try:
            # Validate command for security
            is_valid, error_msg = _validate_command(command)
            if not is_valid:
                return {
                    "error": f"Command validation failed: {error_msg}",
                    "command": command,
                }

            # Default cwd is the session root
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
            os.makedirs(session_root, exist_ok=True)

            if cwd:
                secure_cwd = get_secure_path(cwd, workspace_id, agent_id, session_id)
            else:
                secure_cwd = session_root

            # Parse command safely using shlex (handles quotes properly)
            # This prevents injection while preserving quoted arguments
            try:
                command_parts = shlex.split(command)
            except ValueError as e:
                return {
                    "error": f"Invalid command syntax: {str(e)}",
                    "command": command,
                }

            # Execute with shell=False for security
            # This prevents shell injection attacks
            result = subprocess.run(
                command_parts,  # List, not string - prevents shell injection
                shell=False,  # SECURITY: No shell interpretation
                cwd=secure_cwd,
                capture_output=True,
                text=True,
                timeout=60,
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
            return {"error": "Command timed out after 60 seconds", "command": command}
        except FileNotFoundError:
            return {
                "error": f"Command not found: {shlex.split(command)[0] if command else 'unknown'}",
                "command": command,
            }
        except Exception as e:
            return {"error": f"Failed to execute command: {str(e)}", "command": command}
