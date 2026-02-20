"""Bootstrap: sync a local directory into the agent workspace."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Skip these when copying
SKIP_NAMES = frozenset({".git", "__pycache__", "node_modules", ".venv", ".tox", ".mypy_cache"})


def get_workspace_root(workspace_base: Path | None = None) -> Path:
    """Return the workspace root for this agent (workspace/agent_id/session_id)."""
    if workspace_base is not None:
        return workspace_base / "default" / "codebase_navigator-graph" / "current"
    return (
        Path.home()
        / ".hive"
        / "workdir"
        / "workspaces"
        / "default"
        / "codebase_navigator-graph"
        / "current"
    )


def sync(source_path: Path, workspace_base: Path | None = None) -> int:
    """
    Copy source_path recursively into the agent workspace.
    Clears existing workspace contents first so deletions in source are reflected.
    Skips .git, __pycache__, node_modules, .venv. Returns file count.
    """
    source = source_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source path does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source}")

    dest = get_workspace_root(workspace_base)
    dest.mkdir(parents=True, exist_ok=True)

    # Clear existing contents so deleted files (e.g. tools.py) are removed
    for existing in list(dest.iterdir()):
        try:
            if existing.is_dir():
                shutil.rmtree(existing)
            else:
                existing.unlink()
        except OSError as e:
            logger.debug("Sync clear skip %s: %s", existing.name, e)

    count = 0
    errors = 0
    for item in source.rglob("*"):
        if any(part in SKIP_NAMES for part in item.parts):
            continue
        rel = item.relative_to(source)
        target = dest / rel
        try:
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                count += 1
        except OSError as e:
            errors += 1
            logger.debug("Sync skip %s: %s", rel, e)

    if errors:
        logger.warning("Sync completed with %d skipped files", errors)
    return count
