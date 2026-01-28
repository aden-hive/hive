import os
import subprocess

from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path, validate_command, WORKSPACES_DIR



def register_tools(mcp: FastMCP) -> None:
    """Register command execution tools with the MCP server."""

    @mcp.tool()
    def execute_command_tool(
        command: str, workspace_id: str, agent_id: str, session_id: str, cwd: str | None = None
    ) -> dict:
        """
        Purpose
            Execute a validated shell command within the session sandbox.

        When to use
            Run validators or linters (ruff, mypy, eslint, pytest)
            Generate derived artifacts (indexes, summaries)
            Perform controlled maintenance tasks
            File inspection and text processing

        Allowed Commands
            File inspection: ls, cat, head, tail, find, tree, stat
            Text processing: grep, awk, sed, sort, uniq, cut, diff
            Development: python, node, npm, pip, ruff, pytest, eslint
            Build tools: make, cargo, go
            Utilities: echo, pwd, date, mkdir, touch, cp, mv

        Blocked Operations
            Network access: curl, wget, nc, ssh, ftp
            Destructive: rm -rf, rm -f, chmod, chown
            Shell injection: $(), ``, eval, exec, bash -c
            Sensitive paths: /etc/passwd, ~/.ssh, ~/.aws
            Command chaining: ;, |, &&, ||

        Args:
            command: The shell command to execute (must be in allowed list)
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            cwd: The working directory for the command (relative to session root, optional)

        Returns:
            Dict with command output and execution details, or error dict
        """
        try:
            # Validate command BEFORE execution (defense in depth)
            validation = validate_command(command)
            if not validation.is_valid:
                return {
                    "error": f"Command validation failed: {validation.error}",
                    "command": command,
                    "blocked": True,
                }

            # Default cwd is the session root
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
            os.makedirs(session_root, exist_ok=True)

            if cwd:
                secure_cwd = get_secure_path(cwd, workspace_id, agent_id, session_id)
            else:
                secure_cwd = session_root

            result = subprocess.run(
                command, shell=True, cwd=secure_cwd, capture_output=True, text=True, timeout=60
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
