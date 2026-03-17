"""Worker per-run digest (run diary).

Storage layout:
    ~/.hive/agents/{agent_name}/runs/{run_id}/digest.md

Each completed or failed worker run gets one digest file.  The queen reads
these via get_worker_status(focus='diary') before digging into live runtime
logs — the diary is a cheap, persistent record that survives across sessions.
"""

from __future__ import annotations

import logging
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.runtime.event_bus import AgentEvent, EventBus

logger = logging.getLogger(__name__)


_DIGEST_SYSTEM = """\
You maintain run digests for a worker agent.
A run digest is a concise, factual record of a single task execution.

Write 3-6 sentences covering:
- What the worker was asked to do (the task/goal)
- What approach it took and what tools it used
- What the outcome was (success, partial, or failure — and why if relevant)
- Any notable issues, retries, or escalations to the queen

Write in third person past tense. Be direct and specific.
Omit routine tool invocations unless the result matters.
Output only the digest prose — no headings, no code fences.
"""


def _worker_runs_dir(agent_name: str) -> Path:
    return Path.home() / ".hive" / "agents" / agent_name / "runs"


def digest_path(agent_name: str, run_id: str) -> Path:
    return _worker_runs_dir(agent_name) / run_id / "digest.md"


def _collect_run_events(bus: "EventBus", run_id: str, limit: int = 2000) -> list["AgentEvent"]:
    """Collect all events belonging to *run_id* from the bus history.

    Strategy: find the EXECUTION_STARTED event that carries ``run_id``,
    extract its ``execution_id``, then query the bus by that execution_id.
    This works because TOOL_CALL_*, EDGE_TRAVERSED, NODE_STALLED etc. carry
    execution_id but not run_id.

    Falls back to a full-scan run_id filter when EXECUTION_STARTED is not
    found (e.g. bus was rotated).
    """
    from framework.runtime.event_bus import EventType

    # Pass 1: find execution_id via EXECUTION_STARTED with matching run_id
    started = bus.get_history(event_type=EventType.EXECUTION_STARTED, limit=limit)
    exec_id: str | None = None
    for e in started:
        if getattr(e, "run_id", None) == run_id and e.execution_id:
            exec_id = e.execution_id
            break

    if exec_id:
        return bus.get_history(execution_id=exec_id, limit=limit)

    # Fallback: scan all events and match by run_id attribute
    return [e for e in bus.get_history(limit=limit) if getattr(e, "run_id", None) == run_id]


def _build_run_context(events: list["AgentEvent"], outcome_event: "AgentEvent") -> str:
    """Assemble a plain-text run context string for the digest LLM call."""
    from framework.runtime.event_bus import EventType

    # Reverse so events are in chronological order
    events_chron = list(reversed(events))

    lines: list[str] = []

    # Task input from EXECUTION_STARTED
    started = [e for e in events_chron if e.type == EventType.EXECUTION_STARTED]
    if started:
        inp = started[0].data.get("input", {})
        if inp:
            lines.append(f"Task input: {str(inp)[:400]}")

    # Duration
    if started:
        elapsed = (outcome_event.timestamp - started[0].timestamp).total_seconds()
        m, s = divmod(int(elapsed), 60)
        lines.append(f"Duration: {m}m {s}s" if m else f"Duration: {s}s")

    # Outcome
    if outcome_event.type == EventType.EXECUTION_COMPLETED:
        out = outcome_event.data.get("output", {})
        lines.append(f"Outcome: completed. Output: {str(out)[:300]}" if out else "Outcome: completed.")
    else:
        err = outcome_event.data.get("error", "")
        lines.append(f"Outcome: failed. Error: {str(err)[:300]}" if err else "Outcome: failed.")

    # Node path (edge traversals)
    edges = [e for e in events_chron if e.type == EventType.EDGE_TRAVERSED]
    if edges:
        parts = [f"{e.data.get('source_node','?')}->{e.data.get('target_node','?')}" for e in edges[-20:]]
        lines.append(f"Node path: {', '.join(parts)}")

    # Tools used
    tool_events = [e for e in events_chron if e.type == EventType.TOOL_CALL_COMPLETED]
    if tool_events:
        names = [e.data.get("tool_name", "?") for e in tool_events]
        counts = Counter(names)
        summary = ", ".join(
            f"{name}×{n}" if n > 1 else name for name, n in counts.most_common()
        )
        lines.append(f"Tools used: {summary}")
        # Note any tool errors
        errors = [e for e in tool_events if e.data.get("is_error")]
        if errors:
            err_names = Counter(e.data.get("tool_name", "?") for e in errors)
            lines.append(f"Tool errors: {dict(err_names)}")

    # Issues
    issue_map = {
        EventType.NODE_STALLED: "stall",
        EventType.NODE_TOOL_DOOM_LOOP: "doom loop",
        EventType.CONSTRAINT_VIOLATION: "constraint violation",
        EventType.NODE_RETRY: "retry",
    }
    issue_parts: list[str] = []
    for evt_type, label in issue_map.items():
        n = sum(1 for e in events_chron if e.type == evt_type)
        if n:
            issue_parts.append(f"{n} {label}(s)")
    if issue_parts:
        lines.append(f"Issues: {', '.join(issue_parts)}")

    # Escalations to queen
    escalations = [e for e in events_chron if e.type == EventType.ESCALATION_REQUESTED]
    if escalations:
        lines.append(f"Escalations to queen: {len(escalations)}")

    # Final LLM output snippet (last LLM_TEXT_DELTA snapshot)
    text_events = [
        e for e in reversed(events_chron) if e.type == EventType.LLM_TEXT_DELTA
    ]
    if text_events:
        snapshot = text_events[0].data.get("snapshot", "") or ""
        if snapshot:
            lines.append(f"Final LLM output: {snapshot[-400:].strip()}")

    return "\n".join(lines)


async def consolidate_worker_run(
    agent_name: str,
    run_id: str,
    outcome_event: "AgentEvent",
    bus: "EventBus",
    llm: Any,
) -> None:
    """Write a digest for a completed or failed worker run.

    Called fire-and-forget after EXECUTION_COMPLETED or EXECUTION_FAILED for
    a worker stream.  Failures are logged and silently swallowed so they never
    block the caller.

    Args:
        agent_name: Worker agent directory name (used to determine storage path).
        run_id:     The run ID from the triggering event.
        outcome_event: The EXECUTION_COMPLETED or EXECUTION_FAILED event.
        bus:        The session EventBus (shared queen + worker).
        llm:        LLMProvider with an acomplete() method.
    """
    try:
        events = _collect_run_events(bus, run_id)
        run_context = _build_run_context(events, outcome_event)
        if not run_context:
            logger.debug("worker_memory: no events for run %s, skipping digest", run_id)
            return

        logger.info("worker_memory: generating digest for run %s ...", run_id)

        from framework.agents.queen.config import default_config

        resp = await llm.acomplete(
            messages=[{"role": "user", "content": run_context}],
            system=_DIGEST_SYSTEM,
            max_tokens=min(default_config.max_tokens, 512),
        )
        digest_text = (resp.content or "").strip()
        if not digest_text:
            logger.warning("worker_memory: LLM returned empty digest for run %s", run_id)
            return

        path = digest_path(agent_name, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        from framework.runtime.event_bus import EventType

        ts = outcome_event.timestamp.strftime("%Y-%m-%d %H:%M")
        status = (
            "completed"
            if outcome_event.type == EventType.EXECUTION_COMPLETED
            else "failed"
        )
        path.write_text(
            f"# {run_id}\n\n**{ts}** | {status}\n\n{digest_text}\n",
            encoding="utf-8",
        )
        logger.info(
            "worker_memory: digest written for run %s (%d chars)", run_id, len(digest_text)
        )

    except Exception:
        tb = traceback.format_exc()
        logger.exception("worker_memory: digest failed for run %s", run_id)
        # Persist the error so it's findable without log access
        error_path = _worker_runs_dir(agent_name) / run_id / "digest_error.txt"
        try:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(
                f"run_id: {run_id}\ntime: {datetime.now().isoformat()}\n\n{tb}",
                encoding="utf-8",
            )
        except Exception:
            pass


def read_recent_digests(agent_name: str, max_runs: int = 5) -> list[tuple[str, str]]:
    """Return recent run digests as [(run_id, content), ...], newest first.

    Args:
        agent_name: Worker agent directory name.
        max_runs:   Maximum number of digests to return.

    Returns:
        List of (run_id, digest_content) tuples, ordered newest first.
    """
    runs_dir = _worker_runs_dir(agent_name)
    if not runs_dir.exists():
        return []

    digest_files = sorted(
        runs_dir.glob("*/digest.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_runs]

    result: list[tuple[str, str]] = []
    for f in digest_files:
        try:
            content = f.read_text(encoding="utf-8").strip()
            if content:
                result.append((f.parent.name, content))
        except OSError:
            continue
    return result
