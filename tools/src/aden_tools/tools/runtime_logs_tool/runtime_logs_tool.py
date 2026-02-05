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
import os
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


def register_tools(mcp: FastMCP) -> None:
    """Register runtime log query tools with the MCP server."""

    @mcp.tool()
    def query_runtime_logs(
        agent_work_dir: str,
        status: str = "",
        limit: int = 20,
    ) -> dict:
        """Query runtime log summaries. Returns high-level pass/fail for recent graph runs.

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
        runs_dir = Path(agent_work_dir) / "runtime_logs" / "runs"
        if not runs_dir.exists():
            return {"runs": [], "total": 0, "message": "No runtime logs found"}

        summaries = []
        try:
            entries = os.listdir(runs_dir)
        except OSError:
            return {"runs": [], "total": 0, "error": "Cannot read runs directory"}

        for run_id in entries:
            run_dir = runs_dir / run_id
            if not run_dir.is_dir():
                continue
            summary_path = run_dir / "summary.json"
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

        Args:
            agent_work_dir: Path to the agent's working directory
            run_id: The run ID from query_runtime_logs results
            needs_attention_only: If True, only return flagged nodes
            node_id: If set, only return details for this node

        Returns:
            Dict with run_id and nodes list of per-node details
        """
        details_path = Path(agent_work_dir) / "runtime_logs" / "runs" / run_id / "details.jsonl"
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

        Args:
            agent_work_dir: Path to the agent's working directory
            run_id: The run ID from query_runtime_logs results
            step_index: Specific step index, or -1 for all steps
            node_id: If set, only return steps for this node

        Returns:
            Dict with run_id and steps list of tool/LLM details
        """
        tool_logs_path = Path(agent_work_dir) / "runtime_logs" / "runs" / run_id / "tool_logs.jsonl"
        if not tool_logs_path.exists():
            return {"error": f"No tool logs found for run {run_id}"}

        steps = _read_jsonl(tool_logs_path)

        if node_id:
            steps = [s for s in steps if s.get("node_id") == node_id]

        if step_index >= 0:
            steps = [s for s in steps if s.get("step_index") == step_index]

        return {"run_id": run_id, "steps": steps}
