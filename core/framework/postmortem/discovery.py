"""Locating and loading runtime-log runs from disk.

Runs are written by :class:`framework.tracker.runtime_log_store.RuntimeLogStore`
into either the unified session layout::

    <root>/sessions/<session_id>/logs/{summary.json,details.jsonl,tool_logs.jsonl}

or the deprecated standalone layout::

    <base>/runs/<run_id>/{summary.json,details.jsonl,tool_logs.jsonl}

Agents each get their own storage root (``~/.hive/agents/<name>``), so finding
"the last run" means walking a shallow tree rather than reading one index.
Loading always goes back through ``RuntimeLogStore`` so this module inherits its
corrupt-line tolerance instead of re-implementing the parsers.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from pathlib import Path

from framework.config import HIVE_HOME
from framework.tracker.runtime_log_schemas import NodeDetail, NodeStepLog, RunSummaryLog
from framework.tracker.runtime_log_store import RuntimeLogStore

_LOG_FILES = ("summary.json", "details.jsonl", "tool_logs.jsonl")

# Directory names that never contain runtime logs but can be large. Skipping
# them keeps the walk fast on a busy ~/.hive.
_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "credentials",
        "skills",
        "memories",
        "llm_logs",
        "checkpoints",
        "workspace",
    }
)

# Depth is measured in path segments below the search root. The deepest known
# real layout is agents/<name>/graphs/<id>/sessions/<sid>/logs = 6.
_MAX_DEPTH = 8


@dataclass(frozen=True)
class RunLocation:
    """Where one run's logs live, and how to address it through the store."""

    run_id: str
    logs_dir: Path
    store_base: Path
    mtime: float

    def open_store(self) -> RuntimeLogStore:
        return RuntimeLogStore(self.store_base)


@dataclass
class LoadedRun:
    """The three log levels for a single run, as far as they exist on disk."""

    location: RunLocation
    summary: RunSummaryLog | None
    nodes: list[NodeDetail]
    steps: list[NodeStepLog]


def _dir_mtime(logs_dir: Path) -> float:
    """Newest mtime among the run's log files, falling back to the directory."""
    best = 0.0
    for name in _LOG_FILES:
        path = logs_dir / name
        try:
            best = max(best, path.stat().st_mtime)
        except OSError:
            continue
    if best:
        return best
    try:
        return logs_dir.stat().st_mtime
    except OSError:
        return 0.0


def _has_logs(logs_dir: Path) -> bool:
    return any((logs_dir / name).is_file() for name in _LOG_FILES)


def _location_for(logs_dir: Path) -> RunLocation | None:
    """Build a ``RunLocation`` for a directory holding log files.

    The store addresses runs by id relative to a base path, so recover both
    from the directory's own shape: ``.../sessions/<id>/logs`` is the unified
    layout, ``.../runs/<id>`` the legacy one.
    """
    if not _has_logs(logs_dir):
        return None
    parents = logs_dir.parents
    if logs_dir.name == "logs" and len(parents) >= 3 and parents[1].name == "sessions":
        # <store_base>/sessions/<run_id>/logs
        return RunLocation(logs_dir.parent.name, logs_dir, parents[2], _dir_mtime(logs_dir))
    if len(parents) >= 2 and parents[0].name == "runs":
        # <store_base>/runs/<run_id>  (deprecated)
        return RunLocation(logs_dir.name, logs_dir, parents[1], _dir_mtime(logs_dir))
    return None


def find_runs(root: Path | None = None, limit: int = 50) -> list[RunLocation]:
    """Return run locations under *root*, newest first.

    Defaults to ``~/.hive``. The walk is depth-bounded and prunes directories
    that are known never to hold runtime logs.
    """
    search_root = Path(root) if root is not None else HIVE_HOME
    if not search_root.is_dir():
        return []

    found: list[RunLocation] = []
    # Explicit stack instead of os.walk so depth pruning stays obvious.
    stack: list[tuple[Path, int]] = [(search_root, 0)]
    while stack:
        current, depth = stack.pop()
        location = _location_for(current)
        if location is not None:
            found.append(location)
            # A run directory has no run directories inside it.
            continue
        if depth >= _MAX_DEPTH:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name in _SKIP_DIRS:
                continue
            stack.append((child, depth + 1))

    found.sort(key=lambda loc: loc.mtime, reverse=True)
    return found[:limit] if limit else found


def resolve_run(run_id: str | None, root: Path | None = None) -> RunLocation | None:
    """Find one run by id, or the most recent run when *run_id* is empty.

    An exact id match wins; otherwise a unique suffix/substring match is
    accepted so operators can paste a short prefix of a session id.
    """
    runs = find_runs(root, limit=0)
    if not runs:
        return None
    if not run_id:
        return runs[0]
    for loc in runs:
        if loc.run_id == run_id:
            return loc
    partial = [loc for loc in runs if run_id in loc.run_id]
    return partial[0] if len(partial) == 1 else None


def load_run(location: RunLocation) -> LoadedRun:
    """Read all three log levels for *location*.

    Missing levels come back as ``None``/empty rather than raising: a run that
    crashed before ``end_run()`` has no ``summary.json`` but is exactly the
    kind of run a post-mortem is for.
    """
    store = location.open_store()

    async def _load() -> tuple[RunSummaryLog | None, list[NodeDetail], list[NodeStepLog]]:
        summary = await store.load_summary(location.run_id)
        details = await store.load_details(location.run_id)
        tool_logs = await store.load_tool_logs(location.run_id)
        return (
            summary,
            list(details.nodes) if details else [],
            list(tool_logs.steps) if tool_logs else [],
        )

    with warnings.catch_warnings():
        # The store warns on the legacy runs/ layout; reading old runs is a
        # legitimate thing for a post-mortem to do, so keep the report clean.
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, nodes, steps = asyncio.run(_load())

    return LoadedRun(location=location, summary=summary, nodes=nodes, steps=steps)
