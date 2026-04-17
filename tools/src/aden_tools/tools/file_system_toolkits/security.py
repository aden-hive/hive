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



