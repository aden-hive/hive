import os

# Use user home directory for workspaces
WORKSPACES_DIR = os.path.expanduser("~/.hive/workdir/workspaces")


def get_secure_path(path: str, workspace_id: str, agent_id: str, session_id: str) -> str:
    """Resolve and verify a path within a 3-layer sandbox (workspace/agent/session)."""
    if not workspace_id or not agent_id or not session_id:
        raise ValueError("workspace_id, agent_id, and session_id are all required")

    # Ensure session directory exists
    session_dir = os.path.abspath(os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id))
    os.makedirs(session_dir, exist_ok=True)

    # Normalize whitespace to prevent bypass via leading spaces/tabs
    path = path.strip()

    # Treat both OS-absolute paths AND Unix-style leading slashes as absolute-style
    if os.path.isabs(path) or path.startswith(("/", "\\")):
        # Strip exactly one leading separator to make path relative to session_dir,
        # preserving any subsequent separators (e.g. UNC paths like //server/share)
        rel_path = path[1:] if path and path[0] in ("/", "\\") else path
        final_path = os.path.abspath(os.path.join(session_dir, rel_path))
    else:
        final_path = os.path.abspath(os.path.join(session_dir, path))

    # Verify path is within session_dir
    try:
        common_prefix = os.path.commonpath([final_path, session_dir])
    except ValueError as err:
        # commonpath raises ValueError when paths are on different drives (Windows)
        # or when mixing absolute and relative paths
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.") from err

    if common_prefix != session_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")

    return final_path
