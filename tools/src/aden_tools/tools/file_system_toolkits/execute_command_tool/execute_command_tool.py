import os
import shlex
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

from ..security import WORKSPACES_DIR, get_secure_path


def _parse_command(command: str) -> list[str]:
    """
    Safely parse a command string into arguments.

    Uses shlex.split() for POSIX systems and a Windows-compatible approach
    for Windows to avoid shell injection vulnerabilities.

    Args:
        command: The command string to parse

    Returns:
        List of command arguments
    """
    if sys.platform == "win32":
        # On Windows, use shlex with posix=False for better compatibility
        # This handles Windows-style paths and quoting
        return shlex.split(command, posix=False)
    else:
        # On POSIX systems, use standard shlex parsing
        return shlex.split(command)


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
            No network access unless explicitly allowed
            No destructive commands (rm -rf, system modification)
            Output must be treated as data, not truth

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
            # Default cwd is the session root
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
            os.makedirs(session_root, exist_ok=True)

            if cwd:
                secure_cwd = get_secure_path(cwd, workspace_id, agent_id, session_id)
            else:
                secure_cwd = session_root

            # Parse command safely to prevent shell injection
            # Using shell=False with parsed arguments is more secure
            parsed_command = _parse_command(command)

            result = subprocess.run(
                parsed_command, shell=False, cwd=secure_cwd, capture_output=True, text=True, timeout=60
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
