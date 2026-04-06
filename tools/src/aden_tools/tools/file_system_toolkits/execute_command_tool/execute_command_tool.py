import os
import subprocess

from mcp.server.fastmcp import FastMCP

from ..command_sanitizer import CommandBlockedError, validate_command
from ..security import AGENT_SANDBOXES_DIR, get_sandboxed_path


def register_tools(mcp: FastMCP) -> None:
    """Register command execution tools with the MCP server."""

    @mcp.tool()
    def execute_command_tool(command: str, agent_id: str, cwd: str | None = None) -> dict:
        """
        Purpose
            Execute a shell command within the agent sandbox.

        When to use
            Run validators or linters
            Generate derived artifacts (indexes, summaries)
            Perform controlled maintenance tasks

        Rules & Constraints
            No network access unless explicitly allowed
            No destructive commands (rm -rf, system modification)
            Output must be treated as data, not truth
            Commands are validated against a safety blocklist before execution
            Commands still run through shell=True, so the blocklist only
            prevents explicit nested shell executables; it does not remove
            shell parsing entirely

        Args:
            command: The shell command to execute
            agent_id: The ID of the agent
            cwd: The working directory for the command (relative to agent sandbox, optional)

        Returns:
            Dict with command output and execution details, or error dict
        """
        # Validate command against safety blocklist before execution
        try:
            validate_command(command)
        except CommandBlockedError as e:
            return {"error": f"Command blocked: {e}", "blocked": True}

        try:
            # Default cwd is the agent sandbox root
            agent_root = os.path.join(AGENT_SANDBOXES_DIR, agent_id, "current")
            os.makedirs(agent_root, exist_ok=True)

            if cwd:
                secure_cwd = get_sandboxed_path(cwd, agent_id)
            else:
                secure_cwd = agent_root

            result = subprocess.run(
                command,
                shell=True,
                cwd=secure_cwd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
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
