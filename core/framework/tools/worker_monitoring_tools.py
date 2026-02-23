"""Worker monitoring tools for the Health Judge and Queen triage agents.

Three tools are registered by ``register_worker_monitoring_tools()``:

- ``get_worker_health_summary`` — reads the worker's session log files and
  returns a compact health snapshot (recent verdicts, step count, timing).
  session_id is optional: if omitted, the most recent active session is
  auto-discovered from storage. No agent-side configuration required.
  Used by the Health Judge on every timer tick.

- ``emit_escalation_ticket`` — validates and publishes an EscalationTicket
  to the shared EventBus as a WORKER_ESCALATION_TICKET event.
  Used by the Health Judge when it decides to escalate.

- ``notify_operator`` — emits a QUEEN_INTERVENTION_REQUESTED event so the TUI
  can surface a non-disruptive operator notification.
  Used by the Queen's ticket_triage_node when it decides to intervene.

Usage::

    from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

    register_worker_monitoring_tools(tool_registry, event_bus, storage_path)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)

# How many tool_log steps to include in the health summary
_DEFAULT_LAST_N_STEPS = 40


def register_worker_monitoring_tools(
    registry: "ToolRegistry",
    event_bus: "EventBus",
    storage_path: Path,
    stream_id: str = "worker_health_judge",
    worker_graph_id: str | None = None,
) -> int:
    """Register worker monitoring tools bound to *event_bus* and *storage_path*.

    Args:
        registry: ToolRegistry to register tools on.
        event_bus: The shared EventBus for the worker runtime.
        storage_path: Root storage path of the worker runtime
                      (e.g. ``~/.hive/agents/{name}``).
        stream_id: Stream ID used when emitting events; defaults to judge's stream.
        worker_graph_id: The primary worker graph's ID. Included in health summary
                         so the judge can populate ticket identity fields accurately.

    Returns:
        Number of tools registered.
    """
    from framework.llm.provider import Tool

    storage_path = Path(storage_path)
    # Derive agent identity from storage path so the judge can fill ticket fields.
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

            candidates = [
                d for d in sessions_dir.iterdir()
                if d.is_dir() and (d / "state.json").exists()
            ]
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
            "recent judge verdicts, step count, time since last step, and "
            "a snippet of the most recent LLM output. "
            "session_id is optional — omit it to auto-discover the most recent active session. "
            "Use this on every health check to observe trends."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": (
                        "The worker's active session ID. Omit or pass 'auto' to "
                        "auto-discover the most recent session."
                    ),
                },
                "last_n_steps": {
                    "type": "integer",
                    "description": f"How many recent log steps to include (default {_DEFAULT_LAST_N_STEPS})",
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

    # -------------------------------------------------------------------------
    # emit_escalation_ticket
    # -------------------------------------------------------------------------

    async def emit_escalation_ticket(ticket_json: str) -> str:
        """Validate and publish an EscalationTicket to the shared EventBus.

        ticket_json must be a JSON string containing all required EscalationTicket
        fields. The ticket is validated before publishing — this ensures the judge
        has genuinely filled out all required evidence fields.

        Returns a confirmation JSON with the ticket_id on success, or an error.
        """
        from framework.runtime.escalation_ticket import EscalationTicket

        try:
            raw = json.loads(ticket_json) if isinstance(ticket_json, str) else ticket_json
            ticket = EscalationTicket(**raw)
        except Exception as e:
            return json.dumps({"error": f"Invalid ticket: {e}"})

        try:
            await event_bus.emit_worker_escalation_ticket(
                stream_id=stream_id,
                node_id="judge",
                ticket=ticket.model_dump(),
            )
            logger.info(
                "EscalationTicket emitted: ticket_id=%s severity=%s cause=%r",
                ticket.ticket_id,
                ticket.severity,
                ticket.cause[:80],
            )
            return json.dumps(
                {
                    "status": "emitted",
                    "ticket_id": ticket.ticket_id,
                    "severity": ticket.severity,
                }
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to emit ticket: {e}"})

    _emit_ticket_tool = Tool(
        name="emit_escalation_ticket",
        description=(
            "Validate and publish a structured EscalationTicket to the shared EventBus. "
            "The Queen's ticket_receiver entry point will fire and triage the ticket. "
            "ticket_json must be a JSON string with all required EscalationTicket fields: "
            "worker_agent_id, worker_session_id, worker_node_id, worker_graph_id, "
            "severity (low/medium/high/critical), cause, judge_reasoning, suggested_action, "
            "recent_verdicts (list), total_steps_checked, steps_since_last_accept, "
            "stall_minutes (float or null), evidence_snippet."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_json": {
                    "type": "string",
                    "description": "JSON string of the complete EscalationTicket",
                },
            },
            "required": ["ticket_json"],
        },
    )
    registry.register(
        "emit_escalation_ticket",
        _emit_ticket_tool,
        lambda inputs: emit_escalation_ticket(**inputs),
    )
    tools_registered += 1

    # -------------------------------------------------------------------------
    # notify_operator
    # -------------------------------------------------------------------------

    async def notify_operator(
        ticket_id: str,
        analysis: str,
        urgency: str,
    ) -> str:
        """Emit a QUEEN_INTERVENTION_REQUESTED event to notify the human operator.

        The TUI subscribes to this event and surfaces a non-disruptive dismissable
        notification. The worker agent is NOT paused. The operator can choose to
        open the queen's graph view via Ctrl+Q.

        Args:
            ticket_id: The ticket_id from the original EscalationTicket.
            analysis: 2-3 sentence description of what is wrong, why it matters,
                      and what action is suggested.
            urgency: Severity level: "low", "medium", "high", or "critical".

        Returns:
            Confirmation JSON.
        """
        valid_urgencies = {"low", "medium", "high", "critical"}
        if urgency not in valid_urgencies:
            return json.dumps(
                {"error": f"urgency must be one of {sorted(valid_urgencies)}, got {urgency!r}"}
            )

        try:
            await event_bus.emit_queen_intervention_requested(
                stream_id=stream_id,
                node_id="ticket_triage",
                ticket_id=ticket_id,
                analysis=analysis,
                severity=urgency,
                queen_graph_id="hive_coder_queen",
                queen_stream_id="hive_coder_queen::ticket_receiver",
            )
            logger.info(
                "Queen intervention requested: ticket_id=%s urgency=%s",
                ticket_id,
                urgency,
            )
            return json.dumps(
                {
                    "status": "operator_notified",
                    "ticket_id": ticket_id,
                    "urgency": urgency,
                }
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to notify operator: {e}"})

    _notify_tool = Tool(
        name="notify_operator",
        description=(
            "Notify the human operator that a worker agent needs attention. "
            "This emits a QUEEN_INTERVENTION_REQUESTED event that the TUI surfaces "
            "as a non-disruptive notification. The worker keeps running. "
            "Only call this when you (the Queen) have decided the issue warrants "
            "human attention after reading the escalation ticket."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket_id from the EscalationTicket being triaged",
                },
                "analysis": {
                    "type": "string",
                    "description": (
                        "2-3 sentence analysis: what is wrong, why it matters, "
                        "and what action you suggest."
                    ),
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Severity level for the operator notification",
                },
            },
            "required": ["ticket_id", "analysis", "urgency"],
        },
    )
    registry.register(
        "notify_operator",
        _notify_tool,
        lambda inputs: notify_operator(**inputs),
    )
    tools_registered += 1

    return tools_registered
