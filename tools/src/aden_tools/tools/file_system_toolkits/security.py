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

    # Treat both OS-absolute paths AND Unix-style leading slashes as absolute-style
    if os.path.isabs(path) or path.startswith(("/", "\\")):
        # Strip leading separators so path becomes relative to session_dir
        rel_path = path.lstrip("/\\")
        final_path = os.path.abspath(os.path.join(session_dir, rel_path))
    else:
        final_path = os.path.abspath(os.path.join(session_dir, path))

    # Verify path is within session_dir
    try:
        common_prefix = os.path.commonpath([final_path, session_dir])
    except ValueError:
        # Fails on Windows if paths are on different drives
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")

    if common_prefix != session_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")

    return final_path
