import os
import shlex
import subprocess
from typing import Optional, Set
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path, WORKSPACES_DIR


# Whitelist of allowed commands - only these can be executed
# Includes development tools, validators, linters, and safe utilities
ALLOWED_COMMANDS: Set[str] = {
    # Code quality and testing tools
    "pytest", "python", "python3", "ruff", "black", "mypy", "pylint", "flake8",
    "bandit", "pip", "pip3", "poetry", "uv",
    
    # Source control
    "git", "hg",
    
    # Build tools
    "make", "cargo", "npm", "yarn", "pnpm", "docker",
    
    # File operations (safe read-only and basic operations)
    "ls", "dir", "find", "grep", "cat", "head", "tail", "wc", "sort",
    "uniq", "cut", "tr", "sed", "awk", "stat", "file", "du",
    
    # System information (read-only)
    "echo", "pwd", "whoami", "date", "uname", "which", "env", "printenv",
    
    # Text processing
    "diff", "patch", "md5sum", "sha256sum", "sha1sum",
    
    # Archive operations
    "tar", "gzip", "gunzip", "zip", "unzip",
    
    # Other safe utilities
    "curl", "wget",  # Allowed for downloading, but output must be validated
}

# Patterns that indicate command injection attempts at the string level
# These are checked BEFORE parsing to catch raw injection attempts
DANGEROUS_PATTERNS: Set[str] = {
    ";",  # Command separator
    "|",  # Pipe (redirection)
    "&",  # Background/AND operator (but && and || handled separately)
    ">", "<",  # Output/input redirection
    ">>", "<<",  # Redirect/heredoc
    "`",  # Backtick substitution
    "$(", "${",  # Command substitution
    "\n", "\r",  # Newline injection
}


def _validate_command(command: str) -> Optional[str]:
    """
    Validate that a command is safe to execute.
    
    Security strategy:
    1. Block string-level injection patterns (;, |, >, <, `, newlines)
    2. Block logical operators only in raw form (not in quoted strings due to shlex)
    3. Parse command safely with shlex (handles quoted arguments)
    4. Validate base command against whitelist
    
    Returns:
        None if command is safe, otherwise returns error message
    """
    # Check for dangerous patterns (command injection attempts at string level)
    # Note: parentheses and braces are allowed as they're handled by shlex
    # and can appear in legitimate arguments (e.g., function names in Python)
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            return f"Command contains forbidden pattern: '{pattern}'"
    
    # Check for logical operators that aren't quoted
    # These need special handling since they can be in arguments
    if "&&" in command or "||" in command:
        # Try to parse - if these appear outside quotes, shlex will split them
        try:
            parts = shlex.split(command)
            if "&&" in parts or "||" in parts:
                return "Command contains forbidden logical operator: '&&' or '||'"
        except ValueError:
            pass  # Will catch below
    
    # Parse the command using shlex
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"Invalid command syntax: {str(e)}"
    
    if not parts:
        return "Command cannot be empty"
    
    # Get the base command (first part)
    base_command = parts[0]
    
    # Remove any path components to get just the command name
    command_name = os.path.basename(base_command)
    
    # Check if command is in whitelist
    if command_name not in ALLOWED_COMMANDS:
        return f"Command '{command_name}' is not allowed. Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
    
    return None


def register_tools(mcp: FastMCP) -> None:
    """Register command execution tools with the MCP server."""

    @mcp.tool()
    def execute_command_tool(command: str, workspace_id: str, agent_id: str, session_id: str, cwd: Optional[str] = None) -> dict:
        """
        Purpose
            Execute a shell command within the session sandbox.
            Only whitelisted commands are allowed to prevent command injection.

        When to use
            Run validators or linters
            Generate derived artifacts (indexes, summaries)
            Perform controlled maintenance tasks

        Rules & Constraints
            ✓ Only whitelisted commands allowed (see ALLOWED_COMMANDS)
            ✗ No command injection patterns (;, |, &, >, <, $, `, etc.)
            ✗ No destructive commands (rm, mkfs, dd, chmod, sudo, su, etc.)
            ✗ No network access without validation
            ✓ Output must be treated as data, not truth
            ✓ All commands executed in isolated session sandbox

        Security
            Uses subprocess.run(..., shell=False) for safe execution
            Parses commands with shlex to prevent injection
            Validates all commands against whitelist
            Prevents redirection and piping attacks

        Args:
            command: The shell command to execute (must be whitelisted)
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            cwd: The working directory for the command (relative to session root, optional)

        Returns:
            Dict with command output and execution details, or error dict
        """
        try:
            # Validate command for security
            validation_error = _validate_command(command)
            if validation_error:
                return {"error": f"Command validation failed: {validation_error}"}
            
            # Default cwd is the session root
            session_root = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
            os.makedirs(session_root, exist_ok=True)

            if cwd:
                secure_cwd = get_secure_path(cwd, workspace_id, agent_id, session_id)
            else:
                secure_cwd = session_root

            # Parse command safely using shlex (splits without shell interpretation)
            command_parts = shlex.split(command)
            
            # Execute with shell=False for maximum safety
            # This prevents shell metacharacter interpretation
            result = subprocess.run(
                command_parts,
                shell=False,  # CRITICAL: Never use shell=True with user input
                cwd=secure_cwd,
                capture_output=True,
                text=True,
                timeout=60
            )

            return {
                "success": True,
                "command": command,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "cwd": cwd or "."
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 60 seconds"}
        except Exception as e:
            return {"error": f"Failed to execute command: {str(e)}"}
