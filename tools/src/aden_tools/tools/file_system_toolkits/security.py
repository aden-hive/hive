import os
import re

# Use user home directory for workspaces
WORKSPACES_DIR = os.path.expanduser("~/.hive/workdir/workspaces")

# Pattern to detect Windows drive letters (e.g., C:, D:, Z:)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def get_secure_path(path: str, workspace_id: str, agent_id: str, session_id: str) -> str:
    """Resolve and verify a path within a 3-layer sandbox (workspace/agent/session).

    Security hardening (fixes #2909):
    - Normalizes both '/' and '\\' separators to os.sep on all platforms.
    - Strips ALL leading separators, not just one.
    - Explicitly blocks Windows drive-letter absolute paths (C:, D:, etc.).
    - Rejects null bytes which could truncate paths in C-level file operations.
    """
    if not workspace_id or not agent_id or not session_id:
        raise ValueError("workspace_id, agent_id, and session_id are all required")

    # Ensure session directory exists
    session_dir = os.path.abspath(os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id))
    os.makedirs(session_dir, exist_ok=True)

    # Normalize whitespace to prevent bypass via leading spaces/tabs
    path = path.strip()

    # Reject null bytes — they can truncate paths at the C level
    if "\x00" in path:
        raise ValueError(f"Access denied: Path contains null bytes: '{path}'")

    # Normalize ALL path separators to os.sep so that forward-slash absolute
    # paths on Windows (e.g. C:/Windows) are handled correctly.
    normalized = path.replace("/", os.sep).replace("\\", os.sep)

    # Explicitly block Windows drive-letter paths BEFORE any stripping.
    # After normalizing separators, a path like "C:/foo" becomes "C:\\foo" on Windows.
    # We must reject these because os.path.join ignores the base when the second
    # argument is an absolute path, which would escape the sandbox.
    if _WINDOWS_DRIVE_RE.match(normalized):
        raise ValueError(
            f"Access denied: Absolute paths with drive letters are not allowed: '{path}'"
        )

    # Strip ALL leading separators to make the path relative.
    # This prevents paths like "///etc/passwd" or "\\\\server\\share" from
    # being treated as absolute or UNC paths.
    while normalized and normalized[0] == os.sep:
        normalized = normalized[1:]

    # Collapse redundant separators and resolve '.' components
    normalized = os.path.normpath(normalized) if normalized else ""

    # After normpath, check again for drive letters (normpath can re-introduce them)
    if _WINDOWS_DRIVE_RE.match(normalized):
        raise ValueError(
            f"Access denied: Absolute paths with drive letters are not allowed: '{path}'"
        )

    final_path = os.path.abspath(os.path.join(session_dir, normalized))

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
