"""Worker monitoring tools for Queen runtime inspection.

The following tool is registered by ``register_worker_monitoring_tools()``:

- ``get_worker_health_summary`` — reads the worker's session log files and
  returns a compact health snapshot (recent verdicts, step count, timing).
  session_id is optional: if omitted, the most recent active session is
  auto-discovered from storage.

Usage::

    from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

    register_worker_monitoring_tools(tool_registry, storage_path)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.loader.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# How many tool_log steps to include in the health summary
_DEFAULT_LAST_N_STEPS = 40


def register_worker_monitoring_tools(
    registry: ToolRegistry,
    storage_path: Path,
    worker_graph_id: str | None = None,
    default_session_id: str | None = None,
) -> int:
    """Register worker monitoring tools bound to *storage_path*.

    Args:
        registry: ToolRegistry to register tools on.
        storage_path: Root storage path of the worker runtime
                      (e.g. ``~/.hive/agents/{name}``).
        worker_graph_id: The primary worker graph's ID. Included in health summary
                         so the judge can populate ticket identity fields accurately.
        default_session_id: When set, ``get_worker_health_summary`` uses this
                            session ID as the default instead of auto-discovering
                            the most-recent-by-mtime session. Callers should pass
                            the queen's own session ID so that after a cold-restore
                            the monitoring tool reads the correct worker session
                            rather than a stale orphaned one.

    Returns:
        Number of tools registered.
    """
    from framework.llm.provider import Tool

    storage_path = Path(storage_path)
    # Derive agent identity from storage path for ticket fields.
    # storage_path is ~/.hive/agents/{agent_name} — the name is the last component.
    _worker_agent_id: str = storage_path.name
    _worker_graph_id: str = worker_graph_id or storage_path.name
    tools_registered = 0

    # -------------------------------------------------------------------------
    # get_worker_health_summary
    # -------------------------------------------------------------------------

    async def get_worker_health_summary(
        session_id: str | None = None,
        last_n_steps: int = _DEFAULT_LAST_N_STEPS,
    ) -> str:
        """Read the worker's execution logs and return a compact health snapshot.

        If session_id is omitted or "auto", the most recent active session is
        discovered automatically — no agent-side configuration needed.

        Returns a JSON object with:
        - session_id: the session inspected (useful when auto-discovered)
        - session_status: "running"|"completed"|"failed"|"in_progress"|"unknown"
        - total_steps: total number of log steps recorded so far
        - recent_verdicts: list of last N verdict strings (ACCEPT/RETRY/CONTINUE/ESCALATE)
        - steps_since_last_accept: consecutive non-ACCEPT steps from the end
        - last_step_time_iso: ISO timestamp of the most recent step (or null)
        - stall_minutes: wall-clock minutes since last step (null if < 1 min)
        - evidence_snippet: last LLM text from the most recent step (truncated)
        """
        # Auto-discover the most recent session if not specified
        if not session_id or session_id == "auto":
            sessions_dir = storage_path / "sessions"
            if not sessions_dir.exists():
                return json.dumps({"error": "No sessions found — worker has not started yet"})

            # Prefer the queen's own session ID (set at registration time) over
            # mtime-based discovery, which can pick a stale orphaned session after
            # a cold-restore when a newer-but-empty session directory exists.
            if default_session_id and (sessions_dir / default_session_id).is_dir():
                session_id = default_session_id
            else:
                candidates = [d for d in sessions_dir.iterdir() if d.is_dir() and (d / "state.json").exists()]
                if not candidates:
                    return json.dumps({"error": "No sessions found — worker has not started yet"})

                def _sort_key(d: Path):
                    try:
                        state = json.loads((d / "state.json").read_text(encoding="utf-8"))
                        # in_progress/running sorts before completed/failed
                        priority = 0 if state.get("status", "") in ("in_progress", "running") else 1
                        return (priority, -d.stat().st_mtime)
                    except Exception:
                        return (2, 0)

                candidates.sort(key=_sort_key)
                session_id = candidates[0].name

        # Resolve log paths
        session_dir = storage_path / "sessions" / session_id
        tool_logs_path = session_dir / "logs" / "tool_logs.jsonl"
        state_path = session_dir / "state.json"

        # Read session status
        session_status = "unknown"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                session_status = state.get("status", "unknown")
            except Exception:
                pass

        # Read tool logs
        steps: list[dict] = []
        if tool_logs_path.exists():
            try:
                with open(tool_logs_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                steps.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except OSError as e:
                return json.dumps({"error": f"Could not read tool logs: {e}"})

        total_steps = len(steps)
        recent = steps[-last_n_steps:] if len(steps) > last_n_steps else steps

        # Extract verdict sequence
        recent_verdicts = [s.get("verdict", "") for s in recent if s.get("verdict")]

        # Count consecutive non-ACCEPT from the end
        steps_since_last_accept = 0
        for v in reversed(recent_verdicts):
            if v == "ACCEPT":
                break
            steps_since_last_accept += 1

        # Timing: use tool_logs file mtime as proxy for last step time
        last_step_time_iso: str | None = None
        stall_minutes: float | None = None
        if steps and tool_logs_path.exists():
            try:
                mtime = tool_logs_path.stat().st_mtime
                last_step_time_iso = datetime.fromtimestamp(mtime, UTC).isoformat()
                elapsed = (datetime.now(UTC).timestamp() - mtime) / 60
                stall_minutes = round(elapsed, 1) if elapsed >= 1.0 else None
            except OSError:
                pass

        # Evidence snippet: last LLM text
        evidence_snippet = ""
        for step in reversed(recent):
            text = step.get("llm_text", "")
            if text:
                evidence_snippet = text[:500]
                break

        return json.dumps(
            {
                "worker_agent_id": _worker_agent_id,
                "worker_graph_id": _worker_graph_id,
                "session_id": session_id,
                "session_status": session_status,
                "total_steps": total_steps,
                "recent_verdicts": recent_verdicts,
                "steps_since_last_accept": steps_since_last_accept,
                "last_step_time_iso": last_step_time_iso,
                "stall_minutes": stall_minutes,
                "evidence_snippet": evidence_snippet,
            },
            ensure_ascii=False,
        )

    _health_summary_tool = Tool(
        name="get_worker_health_summary",
        description=(
            "Read the worker agent's execution logs and return a compact health snapshot. "
            "Returns worker_agent_id and worker_graph_id (use these for ticket identity fields), "
            "recent verdicts, step count, time since last step, and "
            "a snippet of the most recent LLM output. "
            "session_id is optional — omit it to auto-discover the most recent active session."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": (
                        "The worker's active session ID. Omit or pass 'auto' to auto-discover the most recent session."
                    ),
                },
                "last_n_steps": {
                    "type": "integer",
                    "description": (f"How many recent log steps to include (default {_DEFAULT_LAST_N_STEPS})"),
                },
            },
            "required": [],
        },
    )
    registry.register(
        "get_worker_health_summary",
        _health_summary_tool,
        lambda inputs: get_worker_health_summary(**inputs),
    )
    tools_registered += 1

    return tools_registered
