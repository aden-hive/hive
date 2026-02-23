"""MCP tools for querying runtime logs.

Three tools provide access to the three-level runtime logging system:
- query_runtime_logs:        Level 1 summaries (did the graph run succeed?)
- query_runtime_log_details: Level 2 per-node results (which node failed?)
- query_runtime_log_raw:     Level 3 full step data (what exactly happened?)

Implementation uses pure sync file I/O -- no imports from the core runtime
logger/store classes. L2 and L3 use JSONL format (one JSON object per line).
L1 uses standard JSON. The file format is the interface between writer
(RuntimeLogger -> RuntimeLogStore) and reader (these MCP tools).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _read_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file into a list of dicts.

    Skips blank lines and corrupt JSON lines (partial writes from crashes).
    """
    results = []
    if not path.exists():
        return results
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping corrupt JSONL line in %s", path)
                    continue
    except OSError as e:
        logger.warning("Failed to read %s: %s", path, e)
    return results


def _get_run_dirs(agent_work_dir: Path) -> list[tuple[str, Path]]:
    """Scan both old and new storage locations for run directories.

    Returns list of (run_id, log_dir_path) tuples.

    Scans:
    - New: {agent_work_dir}/sessions/{session_id}/logs/
    - Old: {agent_work_dir}/runtime_logs/runs/{run_id}/ (deprecated)
    """
    run_dirs = []

    # Scan new location: sessions/{session_id}/logs/
    sessions_dir = agent_work_dir / "sessions"
    if sessions_dir.exists():
        for session_dir in sessions_dir.iterdir():
            if session_dir.is_dir() and session_dir.name.startswith("session_"):
                logs_dir = session_dir / "logs"
                if logs_dir.exists() and logs_dir.is_dir():
                    run_dirs.append((session_dir.name, logs_dir))

    # Scan old location: runtime_logs/runs/ (deprecated)
    old_runs_dir = agent_work_dir / "runtime_logs" / "runs"
    if old_runs_dir.exists():
        for run_dir in old_runs_dir.iterdir():
            if run_dir.is_dir():
                run_dirs.append((run_dir.name, run_dir))

    return run_dirs


def register_tools(mcp: FastMCP) -> None:
    """Register runtime log query tools with the MCP server."""

    @mcp.tool()
    def query_runtime_logs(
        agent_work_dir: str,
        status: str = "",
        limit: int = 20,
    ) -> dict:
        """Query runtime log summaries. Returns high-level pass/fail for recent graph runs.

        Scans both old (runtime_logs/runs/) and new (sessions/*/logs/) locations.
        Use status='needs_attention' to find runs that need debugging.
        Other status values: 'success', 'failure', 'degraded', 'in_progress'.
        Leave status empty to see all runs.

        Args:
            agent_work_dir: Path to the agent's working directory
            status: Filter by status (empty string for all)
            limit: Maximum number of results to return (default 20)

        Returns:
            Dict with 'runs' list of summary objects and 'total' count
        """
        work_dir = Path(agent_work_dir)
        run_dirs = _get_run_dirs(work_dir)

        if not run_dirs:
            return {"runs": [], "total": 0, "message": "No runtime logs found"}

        summaries = []
        for run_id, log_dir in run_dirs:
            summary_path = log_dir / "summary.json"
            if summary_path.exists():
                try:
                    data = json.loads(summary_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
            else:
                # In-progress run: no summary.json yet
                data = {
                    "run_id": run_id,
                    "status": "in_progress",
                    "started_at": "",
                    "needs_attention": False,
                }

            # Apply status filter
            if status == "needs_attention":
                if not data.get("needs_attention", False):
                    continue
            elif status and data.get("status") != status:
                continue

            summaries.append(data)

        # Sort by started_at descending
        summaries.sort(key=lambda s: s.get("started_at", ""), reverse=True)
        total = len(summaries)
        summaries = summaries[:limit]

        return {"runs": summaries, "total": total}

    @mcp.tool()
    def query_runtime_log_details(
        agent_work_dir: str,
        run_id: str,
        needs_attention_only: bool = False,
        node_id: str = "",
    ) -> dict:
        """Get per-node completion details for a specific graph run.

        Shows per-node success/failure, exit status, verdict counts,
        and attention flags. Use after query_runtime_logs identifies
        a run to investigate.

        Supports both old (runtime_logs/runs/) and new (sessions/*/logs/) locations.

        Args:
            agent_work_dir: Path to the agent's working directory
            run_id: The run ID from query_runtime_logs results
            needs_attention_only: If True, only return flagged nodes
            node_id: If set, only return details for this node

        Returns:
            Dict with run_id and nodes list of per-node details
        """
        work_dir = Path(agent_work_dir)

        # Try new location first: sessions/{session_id}/logs/
        if run_id.startswith("session_"):
            details_path = work_dir / "sessions" / run_id / "logs" / "details.jsonl"
        else:
            # Old location: runtime_logs/runs/{run_id}/
            details_path = work_dir / "runtime_logs" / "runs" / run_id / "details.jsonl"

        if not details_path.exists():
            return {"error": f"No details found for run {run_id}"}

        nodes = _read_jsonl(details_path)

        if node_id:
            nodes = [n for n in nodes if n.get("node_id") == node_id]

        if needs_attention_only:
            nodes = [n for n in nodes if n.get("needs_attention")]

        return {"run_id": run_id, "nodes": nodes}

    @mcp.tool()
    def query_runtime_log_raw(
        agent_work_dir: str,
        run_id: str,
        step_index: int = -1,
        node_id: str = "",
    ) -> dict:
        """Get full tool call and LLM details for a graph run.

        Use after identifying a problematic node via
        query_runtime_log_details. Returns tool inputs/outputs,
        LLM text, and token counts per step.

        Supports both old (runtime_logs/runs/) and new (sessions/*/logs/) locations.

        Args:
            agent_work_dir: Path to the agent's working directory
            run_id: The run ID from query_runtime_logs results
            step_index: Specific step index, or -1 for all steps
            node_id: If set, only return steps for this node

        Returns:
            Dict with run_id and steps list of tool/LLM details
        """
        work_dir = Path(agent_work_dir)

        # Try new location first: sessions/{session_id}/logs/
        if run_id.startswith("session_"):
            tool_logs_path = work_dir / "sessions" / run_id / "logs" / "tool_logs.jsonl"
        else:
            # Old location: runtime_logs/runs/{run_id}/
            tool_logs_path = work_dir / "runtime_logs" / "runs" / run_id / "tool_logs.jsonl"

        if not tool_logs_path.exists():
            return {"error": f"No tool logs found for run {run_id}"}

        steps = _read_jsonl(tool_logs_path)

        if node_id:
            steps = [s for s in steps if s.get("node_id") == node_id]

        if step_index >= 0:
            steps = [s for s in steps if s.get("step_index") == step_index]

        return {"run_id": run_id, "steps": steps}
