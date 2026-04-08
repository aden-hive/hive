import os
from pathlib import Path

# Directories that tools are allowed to read/write within.
_ALLOWED_ROOTS: tuple[str, ...] = (
    os.path.expanduser("~/.hive"),
    os.path.expanduser("~/aden/hive/exports"),
)


def resolve_safe_path(path: str) -> str:
    """Resolve *path* to an absolute path and verify it's within allowed roots.

    Accepts both absolute paths and paths relative to ``~/.hive``.
    Raises ``ValueError`` when the resolved path falls outside all
    allowed roots.
    """
    path = path.strip()
    if not path:
        raise ValueError("Path cannot be empty.")

    # Expand ~ and resolve to absolute
    resolved = str(Path(os.path.expanduser(path)).resolve())

    for root in _ALLOWED_ROOTS:
        real_root = os.path.realpath(root)
        if resolved.startswith(real_root + os.sep) or resolved == real_root:
            return resolved

    raise ValueError(
        f"Access denied: '{path}' is outside allowed directories. "
        f"Use absolute paths under ~/.hive/ or exports/."
    )


# Keep the old API for backward compatibility with non-CSV tools.
# TODO: migrate remaining callers and remove.
AGENT_SANDBOXES_DIR = os.path.expanduser("~/.hive/workdir/workspaces/default")


def get_sandboxed_path(path: str, agent_id: str) -> str:
    """Resolve and verify a path within an agent's sandbox directory."""
    if not agent_id:
        raise ValueError("agent_id is required")

    agent_dir = os.path.realpath(os.path.join(AGENT_SANDBOXES_DIR, agent_id, "current"))
    os.makedirs(agent_dir, exist_ok=True)

    path = path.strip()

    if os.path.isabs(path) or path.startswith(("/", "\\")):
        rel_path = path[1:] if path and path[0] in ("/", "\\") else path
        final_path = os.path.realpath(os.path.join(agent_dir, rel_path))
    else:
        final_path = os.path.realpath(os.path.join(agent_dir, path))

    try:
        common_prefix = os.path.commonpath([final_path, agent_dir])
    except ValueError as err:
        raise ValueError(f"Access denied: Path '{path}' is outside the agent sandbox.") from err

    if common_prefix != agent_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the agent sandbox.")

    return final_path
