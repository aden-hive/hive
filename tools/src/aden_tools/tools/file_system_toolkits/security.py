import os

# Use user home directory for workspaces
WORKSPACES_DIR = os.path.expanduser("~/.hive/workdir/workspaces")


def get_secure_path(path: str, workspace_id: str, agent_id: str, session_id: str) -> str:
    """
    Resolve and verify a path within a 3-layer sandbox (workspace/agent/session).

    This function ensures that all file operations are confined to the session
    directory, preventing path traversal attacks and unauthorized file access.

    Security guarantees:
    - Absolute paths with drive letters (Windows) are rejected
    - Path traversal attempts (../) are blocked
    - All paths are normalized to prevent separator confusion
    - Cross-platform compatibility (Windows, Linux, macOS)

    Args:
        path: User-provided file path (relative or absolute)
        workspace_id: Workspace identifier
        agent_id: Agent identifier
        session_id: Session identifier

    Returns:
        Absolute path within the session sandbox

    Raises:
        ValueError: If path escapes sandbox or contains invalid components

    Examples:
        >>> get_secure_path("data.csv", "ws1", "agent1", "session1")
        "/home/user/.hive/workdir/workspaces/ws1/agent1/session1/data.csv"

        >>> get_secure_path("C:/Windows/System32", "ws1", "agent1", "session1")
        ValueError: Access denied: Absolute paths with drive letters are not allowed
    """
    if not workspace_id or not agent_id or not session_id:
        raise ValueError("workspace_id, agent_id, and session_id are all required")

    # Ensure session directory exists
    session_dir = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Normalize path separators to handle both / and \ on all platforms
    # This is critical for security on Windows where paths can use either separator
    normalized_path = path.replace("/", os.sep).replace("\\", os.sep)

    # Strip all leading separators (handles Unix-style absolute paths like /etc/passwd)
    while normalized_path.startswith(os.sep):
        normalized_path = normalized_path[1:]

    # Check for Windows drive letters (e.g., C:, D:)
    # This prevents paths like "C:/Windows" from escaping the sandbox
    if len(normalized_path) >= 2 and normalized_path[1] == ":":
        raise ValueError(
            f"Access denied: Absolute paths with drive letters are not allowed: '{path}'"
        )

    # Resolve to absolute path within session directory
    final_path = os.path.abspath(os.path.join(session_dir, normalized_path))

    # Verify path is within session_dir using commonpath
    try:
        common_prefix = os.path.commonpath([final_path, session_dir])
    except ValueError:
        # Different drives on Windows (e.g., C: vs D:)
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.") from None

    if common_prefix != session_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")

    return final_path
