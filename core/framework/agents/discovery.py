"""Agent discovery — scan known directories and return categorised AgentEntry lists."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path


@dataclass
class WorkerEntry:
    """A single worker within a colony."""

    name: str
    config_path: Path
    description: str = ""
    tool_count: int = 0
    task: str = ""
    spawned_at: str = ""
    queen_name: str = ""
    colony_id: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "config_path": str(self.config_path),
            "description": self.description,
            "tool_count": self.tool_count,
            "task": self.task,
            "spawned_at": self.spawned_at,
            "queen_name": self.queen_name,
            "colony_id": self.colony_id,
        }


@dataclass
class AgentEntry:
    """Lightweight agent metadata for the picker / API discover endpoint."""

    path: Path
    name: str
    description: str
    category: str
    session_count: int = 0
    run_count: int = 0
    node_count: int = 0
    tool_count: int = 0
    tags: list[str] = field(default_factory=list)
    last_active: str | None = None
    created_at: str | None = None
    icon: str | None = None
    workers: list[WorkerEntry] = field(default_factory=list)


def _get_last_active(agent_path: Path) -> str | None:
    """Return the most recent updated_at timestamp across all sessions.

    Checks both worker sessions (``colonies/<c>/workers/<sid>/``) and
    queen-as-overseer sessions (``colonies/<c>/queens/<q>/sessions/<sid>/``)
    for this colony.
    """
    from datetime import datetime

    latest: str | None = None

    # 1. Worker sessions live under colonies/<c>/workers/<sid>/.
    workers_root = agent_path / "workers"
    if workers_root.exists():
        for session_dir in workers_root.iterdir():
            if not session_dir.is_dir():
                continue
            state_file = session_dir / "state.json"
            if not state_file.exists():
                continue
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                ts = data.get("timestamps", {}).get("updated_at")
                if ts and (latest is None or ts > latest):
                    latest = ts
            except Exception:
                continue

    # 2. Queen-as-overseer sessions live under
    # colonies/<c>/queens/<queen>/sessions/<sid>/.
    queens_root = agent_path / "queens"
    if queens_root.exists():
        for queen_dir in queens_root.iterdir():
            if not queen_dir.is_dir():
                continue
            sessions_root = queen_dir / "sessions"
            if not sessions_root.is_dir():
                continue
            for session_dir in sessions_root.iterdir():
                if not session_dir.is_dir():
                    continue
                try:
                    ts = datetime.fromtimestamp(session_dir.stat().st_mtime).isoformat()
                    if latest is None or ts > latest:
                        latest = ts
                except OSError:
                    continue

    return latest


def _count_sessions(agent_name: str) -> int:
    """Count colony queen+worker session directories for the given colony."""
    from framework.config import colony_dir

    cdir = colony_dir(agent_name)
    if not cdir.exists():
        return 0
    n = 0
    # workers/<sid>/
    workers_dir = cdir / "workers"
    if workers_dir.exists():
        n += sum(1 for d in workers_dir.iterdir() if d.is_dir())
    # queens/<queen>/sessions/<sid>/
    queens_dir = cdir / "queens"
    if queens_dir.exists():
        for q in queens_dir.iterdir():
            if not q.is_dir():
                continue
            sess = q / "sessions"
            if sess.exists():
                n += sum(1 for d in sess.iterdir() if d.is_dir())
    return n


def _count_runs(agent_name: str) -> int:
    """Count unique run_ids across all worker sessions for a colony."""
    from framework.config import colony_workers_dir

    sessions_dir = colony_workers_dir(agent_name)
    if not sessions_dir.exists():
        return 0
    run_ids: set[str] = set()
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir() or not session_dir.name.startswith("session_"):
            continue
        # runs.jsonl lives inside workspace subdirectories
        for runs_file in session_dir.rglob("runs.jsonl"):
            try:
                for line in runs_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    rid = record.get("run_id")
                    if rid:
                        run_ids.add(rid)
            except Exception:
                continue
    return len(run_ids)


_EXCLUDED_JSON_STEMS = {"agent", "flowchart", "triggers", "configuration", "metadata", "tasks"}


def _is_colony_dir(path: Path) -> bool:
    """Check if a directory is a colony with worker config files."""
    if not path.is_dir():
        return False
    return any(f.suffix == ".json" and f.stem not in _EXCLUDED_JSON_STEMS for f in path.iterdir() if f.is_file())


def _find_worker_configs(colony_dir: Path) -> list[Path]:
    """Find all worker config JSON files in a colony directory."""
    return sorted(p for p in colony_dir.iterdir() if p.is_file() and p.suffix == ".json" and p.stem not in _EXCLUDED_JSON_STEMS)


def _extract_agent_stats(agent_path: Path) -> tuple[int, int, list[str]]:
    """Extract worker count, tool count, and tags from a colony directory."""
    tags: list[str] = []

    worker_configs = _find_worker_configs(agent_path)
    if worker_configs:
        all_tools: set[str] = set()
        for wc_path in worker_configs:
            try:
                data = json.loads(wc_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    tools = data.get("tools", [])
                    if isinstance(tools, list):
                        all_tools.update(tools)
            except Exception:
                pass
        return len(worker_configs), len(all_tools), tags

    return 0, 0, tags


def discover_agents() -> dict[str, list[AgentEntry]]:
    """Discover agents from all known sources grouped by category."""
    from framework.config import COLONIES_DIR

    groups: dict[str, list[AgentEntry]] = {}
    sources = [
        ("Your Agents", COLONIES_DIR),
    ]

    # Track seen agent directory names to avoid duplicates when the same
    # agent exists in both colonies/ and exports/ (colonies takes priority).
    _seen_agent_names: set[str] = set()

    for category, base_dir in sources:
        if not base_dir.exists():
            continue
        entries: list[AgentEntry] = []
        for path in sorted(base_dir.iterdir(), key=lambda p: p.name):
            if not _is_colony_dir(path):
                continue
            if path.name in _seen_agent_names:
                continue
            _seen_agent_names.add(path.name)

            config_fallback_name = path.name.replace("_", " ").title()
            name = config_fallback_name
            desc = ""

            # Read colony metadata for queen provenance and timestamps
            colony_queen_name = ""
            colony_created_at: str | None = None
            colony_icon: str | None = None
            colony_deleted = False
            metadata_path = path / "metadata.json"
            if metadata_path.exists():
                try:
                    mdata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    colony_queen_name = mdata.get("queen_name", "")
                    colony_created_at = mdata.get("created_at")
                    colony_icon = mdata.get("icon")
                    colony_deleted = bool(mdata.get("deleted"))
                except Exception:
                    pass
            # Soft-deleted colonies stay on disk but are hidden from discovery.
            if colony_deleted:
                continue
            # Fallback: use directory creation time if metadata lacks created_at
            if not colony_created_at:
                try:
                    from datetime import datetime

                    stat = path.stat()
                    colony_created_at = datetime.fromtimestamp(stat.st_birthtime, tz=UTC).isoformat()
                except Exception:
                    pass

            worker_entries: list[WorkerEntry] = []
            worker_configs = _find_worker_configs(path)
            for wc_path in worker_configs:
                try:
                    data = json.loads(wc_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        w = WorkerEntry(
                            name=data.get("name", wc_path.stem),
                            config_path=wc_path,
                            description=data.get("description", ""),
                            tool_count=len(data.get("tools", [])),
                            task=data.get("goal", {}).get("description", ""),
                            spawned_at=data.get("spawned_at", ""),
                            queen_name=colony_queen_name,
                            colony_id=path.name,
                        )
                        worker_entries.append(w)
                        if not desc:
                            desc = data.get("description", "")
                except Exception:
                    pass

            node_count = len(worker_entries)
            tool_count = max((w.tool_count for w in worker_entries), default=0)

            entries.append(
                AgentEntry(
                    path=path,
                    name=name,
                    description=desc,
                    category=category,
                    session_count=_count_sessions(path.name),
                    run_count=_count_runs(path.name),
                    node_count=node_count,
                    tool_count=tool_count,
                    tags=[],
                    last_active=_get_last_active(path),
                    created_at=colony_created_at,
                    icon=colony_icon,
                    workers=worker_entries,
                )
            )
        if entries:
            existing = groups.get(category, [])
            existing.extend(entries)
            groups[category] = existing

    return groups
