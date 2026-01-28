import os
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Use user home directory for workspaces
WORKSPACES_DIR = os.path.expanduser("~/.hive/workdir/workspaces")

# Command security configuration
# Allowed base commands (the first word of the command)
ALLOWED_COMMANDS: set[str] = {
    # File inspection (read-only)
    "ls", "cat", "head", "tail", "wc", "file", "stat", "find", "tree",
    # Text processing
    "grep", "awk", "sed", "sort", "uniq", "cut", "tr", "diff",
    # Development tools
    "python", "python3", "node", "npm", "npx", "pip", "pip3",
    "ruff", "black", "mypy", "pytest", "eslint", "prettier",
    # Build tools
    "make", "cargo", "go", "rustc", "gcc", "g++",
    # Safe utilities
    "echo", "printf", "pwd", "date", "env", "which", "whoami",
    "basename", "dirname", "realpath", "mkdir", "touch", "cp", "mv",
    # JSON/data processing
    "jq", "yq",
}

# Patterns that are always blocked (security risks)
BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # Network access
    (r"\bcurl\b", "Network access (curl) is not allowed"),
    (r"\bwget\b", "Network access (wget) is not allowed"),
    (r"\bnc\b", "Network access (netcat) is not allowed"),
    (r"\bnetcat\b", "Network access (netcat) is not allowed"),
    (r"\bssh\b", "SSH access is not allowed"),
    (r"\bscp\b", "SCP access is not allowed"),
    (r"\bsftp\b", "SFTP access is not allowed"),
    (r"\bftp\b", "FTP access is not allowed"),
    (r"\btelnet\b", "Telnet access is not allowed"),
    
    # Destructive commands
    (r"\brm\s+(-[a-zA-Z]*)?r", "Recursive delete (rm -r) is not allowed"),
    (r"\brm\s+(-[a-zA-Z]*)?f", "Force delete (rm -f) is not allowed"),
    (r":>\s*\S+", "File truncation is not allowed"),
    (r">\s*/", "Writing to absolute paths is not allowed"),
    
    # Privilege escalation
    (r"\bsudo\b", "Privilege escalation (sudo) is not allowed"),
    (r"\bsu\b", "User switching (su) is not allowed"),
    (r"\bchmod\b", "Permission changes (chmod) are not allowed"),
    (r"\bchown\b", "Ownership changes (chown) are not allowed"),
    (r"\bchgrp\b", "Group changes (chgrp) are not allowed"),
    
    # Shell injection vectors
    (r"\$\(", "Command substitution $() is not allowed"),
    (r"`[^`]+`", "Backtick command substitution is not allowed"),
    (r"\beval\b", "eval is not allowed"),
    (r"\bexec\b", "exec is not allowed"),
    (r"\bsource\b", "source is not allowed"),
    (r"\bbash\s+-c\b", "bash -c is not allowed"),
    (r"\bsh\s+-c\b", "sh -c is not allowed"),
    
    # Sensitive file access
    (r"/etc/passwd", "Access to /etc/passwd is not allowed"),
    (r"/etc/shadow", "Access to /etc/shadow is not allowed"),
    (r"~/\.ssh", "Access to SSH keys is not allowed"),
    (r"~/\.aws", "Access to AWS credentials is not allowed"),
    (r"~/\.git", "Access to git config is not allowed"),
    (r"/proc/", "Access to /proc is not allowed"),
    (r"/sys/", "Access to /sys is not allowed"),
    
    # Reverse shells and persistence
    (r"/dev/tcp", "Network device access is not allowed"),
    (r"/dev/udp", "Network device access is not allowed"),
    (r"\bmkfifo\b", "Named pipes (mkfifo) are not allowed"),
    (r"\bcron", "Cron access is not allowed"),
    (r"\bat\b", "at scheduler is not allowed"),
]

# Operators that could enable chaining attacks (more restrictive)
DANGEROUS_OPERATORS: list[tuple[str, str]] = [
    (r";\s*\S", "Command chaining with ; is not allowed"),
    (r"\|\s*\S", "Piping is not allowed for security"),
    (r"&&\s*\S", "Command chaining with && is not allowed"),
    (r"\|\|\s*\S", "Command chaining with || is not allowed"),
]


@dataclass
class CommandValidationResult:
    """Result of command validation."""
    is_valid: bool
    error: str | None = None
    command: str = ""
    base_command: str = ""


def validate_command(command: str, allow_pipes: bool = False) -> CommandValidationResult:
    """
    Validate a shell command for security.
    
    This implements defense-in-depth: even in Docker, we validate commands
    to prevent abuse, provide audit trails, and catch LLM hallucinations.
    
    Args:
        command: The shell command to validate
        allow_pipes: If True, allow safe piping (e.g., grep | head)
        
    Returns:
        CommandValidationResult with validation status and error message
    """
    if not command or not command.strip():
        return CommandValidationResult(
            is_valid=False,
            error="Empty command",
            command=command,
        )
    
    command = command.strip()
    
    # Extract base command (first word, handle paths like /usr/bin/python)
    parts = command.split()
    base_command = os.path.basename(parts[0]) if parts else ""
    
    # Check against blocked patterns first (highest priority)
    for pattern, message in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            logger.warning(f"Command blocked: {message} - Command: {command[:100]}")
            return CommandValidationResult(
                is_valid=False,
                error=message,
                command=command,
                base_command=base_command,
            )
    
    # Check dangerous operators (unless pipes explicitly allowed)
    operators_to_check = DANGEROUS_OPERATORS
    if allow_pipes:
        # Only check non-pipe operators
        operators_to_check = [op for op in DANGEROUS_OPERATORS if "Piping" not in op[1]]
    
    for pattern, message in operators_to_check:
        if re.search(pattern, command):
            logger.warning(f"Command blocked: {message} - Command: {command[:100]}")
            return CommandValidationResult(
                is_valid=False,
                error=message,
                command=command,
                base_command=base_command,
            )
    
    # Check whitelist
    if base_command not in ALLOWED_COMMANDS:
        logger.warning(f"Command not in whitelist: {base_command} - Command: {command[:100]}")
        return CommandValidationResult(
            is_valid=False,
            error=f"Command '{base_command}' is not in the allowed commands list",
            command=command,
            base_command=base_command,
        )
    
    logger.info(f"Command validated: {base_command} - {command[:50]}...")
    return CommandValidationResult(
        is_valid=True,
        command=command,
        base_command=base_command,
    )


def get_secure_path(path: str, workspace_id: str, agent_id: str, session_id: str) -> str:
    """Resolve and verify a path within a 3-layer sandbox (workspace/agent/session)."""
    if not workspace_id or not agent_id or not session_id:
        raise ValueError("workspace_id, agent_id, and session_id are all required")

    # Ensure session directory exists: runtime/workspace_id/agent_id/session_id
    session_dir = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Resolve absolute path
    if os.path.isabs(path):
        # Treat absolute paths as relative to the session root if they start with /
        rel_path = path.lstrip(os.sep)
        final_path = os.path.abspath(os.path.join(session_dir, rel_path))
    else:
        final_path = os.path.abspath(os.path.join(session_dir, path))

    # Verify path is within session_dir
    common_prefix = os.path.commonpath([final_path, session_dir])
    if common_prefix != session_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")

    return final_path
