import os

# Base directory for agent sandboxes
AGENT_SANDBOXES_DIR = os.path.expanduser("~/.hive/workdir/workspaces/default")


def get_sandboxed_path(path: str, agent_id: str) -> str:
    """Resolve and verify a path within an agent's sandbox directory."""
    if not agent_id:
        raise ValueError("agent_id is required")

    # Ensure agent directory exists
    agent_dir = os.path.realpath(os.path.join(AGENT_SANDBOXES_DIR, agent_id, "current"))
    os.makedirs(agent_dir, exist_ok=True)

    # Normalize whitespace to prevent bypass via leading spaces/tabs
    path = path.strip()

    # Treat both OS-absolute paths AND Unix-style leading slashes as absolute-style
    if os.path.isabs(path) or path.startswith(("/", "\\")):
        # Strip exactly one leading separator to make path relative to agent_dir,
        # preserving any subsequent separators (e.g. UNC paths like //server/share)
        rel_path = path[1:] if path and path[0] in ("/", "\\") else path
        final_path = os.path.realpath(os.path.join(agent_dir, rel_path))
    else:
        final_path = os.path.realpath(os.path.join(agent_dir, path))

    # Verify path is within agent_dir
    try:
        common_prefix = os.path.commonpath([final_path, agent_dir])
    except ValueError as err:
        # commonpath raises ValueError when paths are on different drives (Windows)
        # or when mixing absolute and relative paths
        raise ValueError(f"Access denied: Path '{path}' is outside the agent sandbox.") from err

    if common_prefix != agent_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the agent sandbox.")

    return final_path
