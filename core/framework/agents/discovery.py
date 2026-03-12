"""Agent discovery — scan known directories and return categorised AgentEntry lists."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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


def _get_last_active(agent_name: str) -> str | None:
    """Return the most recent updated_at timestamp across all sessions."""
    sessions_dir = Path.home() / ".hive" / "agents" / agent_name / "sessions"
    if not sessions_dir.exists():
        return None
    latest: str | None = None
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir() or not session_dir.name.startswith("session_"):
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
    return latest


def _count_sessions(agent_name: str) -> int:
    """Count session directories under ~/.hive/agents/{agent_name}/sessions/."""
    sessions_dir = Path.home() / ".hive" / "agents" / agent_name / "sessions"
    if not sessions_dir.exists():
        return 0
    return sum(1 for d in sessions_dir.iterdir() if d.is_dir() and d.name.startswith("session_"))


def _count_runs(agent_name: str) -> int:
    """Count unique run_ids across all sessions for an agent."""
    sessions_dir = Path.home() / ".hive" / "agents" / agent_name / "sessions"
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


def _extract_agent_stats(agent_path: Path) -> tuple[int, int, list[str]]:
    """Extract node count, tool count, and tags from an agent directory.

    Prefers agent.py (AST-parsed) over agent.json for node/tool counts
    since agent.json may be stale.  Tags are only available from agent.json.
    """
    import ast

    node_count, tool_count, tags = 0, 0, []

    agent_py = agent_path / "agent.py"
    if agent_py.exists():
        try:
            tree = ast.parse(agent_py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "nodes":
                            if isinstance(node.value, ast.List):
                                node_count = len(node.value.elts)
        except Exception:
            pass

    agent_json = agent_path / "agent.json"
    if agent_json.exists():
        try:
            data = json.loads(agent_json.read_text(encoding="utf-8"))
            json_nodes = data.get("nodes", [])
            if node_count == 0:
                node_count = len(json_nodes)
            tools: set[str] = set()
            for n in json_nodes:
                tools.update(n.get("tools", []))
            tool_count = len(tools)
            tags = data.get("agent", {}).get("tags", [])
        except Exception:
            pass

    return node_count, tool_count, tags


def discover_agents() -> dict[str, list[AgentEntry]]:
    """Discover agents from all known sources grouped by category."""
    from framework.runner.cli import (
        _extract_python_agent_metadata,
        _get_framework_agents_dir,
        _is_valid_agent_dir,
    )

    groups: dict[str, list[AgentEntry]] = {}
    sources = [
        ("Your Agents", Path("exports")),
        ("Framework", _get_framework_agents_dir()),
        ("Examples", Path("examples/templates")),
    ]

    for category, base_dir in sources:
        if not base_dir.exists():
            continue
        entries: list[AgentEntry] = []
        for path in sorted(base_dir.iterdir(), key=lambda p: p.name):
            if not _is_valid_agent_dir(path):
                continue

            name, desc = _extract_python_agent_metadata(path)
            config_fallback_name = path.name.replace("_", " ").title()
            used_config = name != config_fallback_name

            node_count, tool_count, tags = _extract_agent_stats(path)
            if not used_config:
                agent_json = path / "agent.json"
                if agent_json.exists():
                    try:
                        data = json.loads(agent_json.read_text(encoding="utf-8"))
                        meta = data.get("agent", {})
                        name = meta.get("name", name)
                        desc = meta.get("description", desc)
                    except Exception:
                        pass

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
                    tags=tags,
                    last_active=_get_last_active(path.name),
                )
            )
        if entries:
            groups[category] = entries

    return groups
