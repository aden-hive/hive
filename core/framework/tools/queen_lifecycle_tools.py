"""Queen lifecycle tools for colony management.

These tools give the Queen agent control over colony workers.
They close over a session-like object that provides ``colony_runtime``,
allowing late-binding access to the runtime (which may be loaded/unloaded
dynamically).

Usage::

    from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

    # Server path — pass a Session object
    register_queen_lifecycle_tools(
        registry=queen_tool_registry,
        session=session,
        session_id=session.id,
    )

    # TUI path — wrap bare references in an adapter
    from framework.tools.queen_lifecycle_tools import WorkerSessionAdapter

    adapter = WorkerSessionAdapter(
        colony_runtime=runtime,
        event_bus=event_bus,
        worker_path=storage_path,
    )
    register_queen_lifecycle_tools(
        registry=queen_tool_registry,
        session=adapter,
        session_id=session_id,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.credentials.models import CredentialError
from framework.host.event_bus import AgentEvent, EventType
from framework.loader.preload_validation import credential_errors_to_json
from framework.server.app import validate_agent_path
from framework.tools.flowchart_utils import (
    FLOWCHART_TYPES,
    classify_flowchart_node,
    load_flowchart_file,
    save_flowchart_file,
    synthesize_draft_from_runtime,
)

if TYPE_CHECKING:
    from framework.host.agent_host import AgentHost
    from framework.host.colony_runtime import ColonyRuntime
    from framework.host.event_bus import EventBus
    from framework.loader.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def _render_credentials_block(provider: Any) -> str:
    """Call a credentials_prompt_provider safely and return its output.

    Returns "" if no provider is set or if it raises (the Queen prompt must
    never fail to render because credential discovery hit a hiccup).
    """
    if provider is None:
        return ""
    try:
        result = provider()
    except Exception:
        logger.debug("credentials_prompt_provider raised", exc_info=True)
        return ""
    return result or ""


@dataclass
class WorkerSessionAdapter:
    """Adapter for TUI compatibility.

    Wraps bare colony_runtime + event_bus + storage_path into a
    session-like object that queen lifecycle tools can use.
    """

    colony_runtime: Any  # ColonyRuntime
    event_bus: Any  # EventBus
    worker_path: Path | None = None


@dataclass
class QueenPhaseState:
    """Mutable state container for queen operating phase.

    Three phases: independent, working, reviewing.
    INDEPENDENT: queen acts as a standalone agent with MCP tools, no colony workers.
    WORKING: colony workers are running autonomously.
    REVIEWING: workers have completed, queen reviews results.

    Shared between the dynamic_tools_provider callback and tool handlers
    that trigger phase transitions.
    """

    phase: str = "independent"  # "independent", "working", or "reviewing"
    independent_tools: list = field(default_factory=list)  # list[Tool]
    working_tools: list = field(default_factory=list)  # list[Tool]
    reviewing_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_PHASE_CHANGED events

    # Agent path — set after colony bootstrap so the frontend can query credentials
    agent_path: str | None = None

    # Phase-specific prompts (set by queen_orchestrator after construction)
    prompt_independent: str = ""
    prompt_working: str = ""
    prompt_reviewing: str = ""

    # Default skill operational protocols — appended to every phase prompt
    protocols_prompt: str = ""
    # Community skills catalog (XML) — appended after protocols
    skills_catalog_prompt: str = ""
    # Optional SkillsManager reference. When set, get_current_prompt()
    # re-renders the catalog filtered by the current phase so skills
    # whose frontmatter `visibility` list excludes this phase are
    # dropped (shaves ~1 KB of DM-irrelevant framework skills on
    # independent-phase turns).
    skills_manager: Any = None

    # Provider for the ambient "Connected integrations" block. The orchestrator
    # wires this to a function that snapshots CredentialStoreAdapter accounts
    # and renders them via build_accounts_prompt(). Called on every prompt
    # rebuild so newly added/deleted credentials show up without restart.
    credentials_prompt_provider: Any = None  # Callable[[], str] | None

    # Queen identity (set once at session start by queen identity hook,
    # persisted here so it survives dynamic prompt refreshes across iterations).
    queen_id: str | None = None
    queen_profile: dict | None = None
    queen_identity_prompt: str = ""

    # Cached recall blocks — populated async by recall_selector after each turn.
    _cached_global_recall_block: str = ""
    _cached_queen_recall_block: str = ""
    # Memory directories.
    global_memory_dir: Path | None = None
    queen_memory_dir: Path | None = None

    async def switch_to_working(self, source: str = "tool") -> None:
        """Switch to working phase — colony workers are running.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "working":
            return
        self.phase = "working"
        tool_names = [t.name for t in self.working_tools]
        logger.info("Queen phase → working (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to WORKING phase. "
                "Colony workers are running. Available tools: " + ", ".join(tool_names) + "."
            )

    def get_current_tools(self) -> list:
        """Return tools for the current phase."""
        if self.phase == "working":
            return list(self.working_tools)
        if self.phase == "reviewing":
            return list(self.reviewing_tools)
        # Default / "independent" — DM mode with full MCP tools.
        return list(self.independent_tools)

    def get_current_prompt(self) -> str:
        """Return the system prompt for the current phase."""
        if self.phase == "working":
            base = self.prompt_working
        elif self.phase == "reviewing":
            base = self.prompt_reviewing
        else:
            base = self.prompt_independent

        parts = []
        if self.queen_identity_prompt:
            parts.append(self.queen_identity_prompt)
        parts.append(base)
        credentials_block = _render_credentials_block(self.credentials_prompt_provider)
        if credentials_block:
            parts.append(credentials_block)
        catalog_prompt = self.skills_catalog_prompt
        if self.skills_manager is not None:
            try:
                catalog_prompt = self.skills_manager.skills_catalog_prompt_for_phase(self.phase)
            except Exception:
                catalog_prompt = self.skills_catalog_prompt
        if catalog_prompt:
            parts.append(catalog_prompt)
        if self.protocols_prompt:
            parts.append(self.protocols_prompt)
        if self._cached_global_recall_block:
            parts.append(self._cached_global_recall_block)
        if self._cached_queen_recall_block:
            parts.append(self._cached_queen_recall_block)
        return "\n\n".join(parts)

    async def _emit_phase_event(self) -> None:
        """Publish a QUEEN_PHASE_CHANGED event so the frontend updates the tag."""
        if self.event_bus is not None:
            data: dict = {"phase": self.phase}
            if self.agent_path:
                data["agent_path"] = self.agent_path
            await self.event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_PHASE_CHANGED,
                    stream_id="queen",
                    data=data,
                )
            )

    async def switch_to_reviewing(self, source: str = "tool") -> None:
        """Switch to reviewing phase — colony workers have finished, queen summarises.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "reviewing":
            return
        self.phase = "reviewing"
        tool_names = [t.name for t in self.reviewing_tools]
        logger.info("Queen phase → reviewing (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to REVIEWING phase. "
                "Workers have finished. Summarise results, answer follow-ups, "
                "and help the user decide next steps. "
                "Available tools: " + ", ".join(tool_names) + "."
            )

    async def switch_to_independent(self, source: str = "tool") -> None:
        """Switch to independent phase — queen acts as standalone agent.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "independent":
            return
        self.phase = "independent"
        tool_names = [t.name for t in self.independent_tools]
        logger.info("Queen phase → independent (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to INDEPENDENT mode. "
                "You are the agent — execute the task directly. "
                "Available tools: " + ", ".join(tool_names) + "."
            )


def build_worker_profile(runtime: Any, agent_path: Path | str | None = None) -> str:
    """Build a worker capability profile from the runtime's spec and goal."""
    goal = runtime._goal if hasattr(runtime, "_goal") else runtime.goal

    lines = ["\n\n# Worker Profile"]
    colony_id = getattr(runtime, "colony_id", None) or ""
    if colony_id:
        lines.append(f"Agent: {colony_id}")
    if agent_path:
        lines.append(f"Path: {agent_path}")
    lines.append(f"Goal: {goal.name}")
    if goal.description:
        lines.append(f"Description: {goal.description}")

    if goal.success_criteria:
        lines.append("\n## Success Criteria")
        for sc in goal.success_criteria:
            lines.append(f"- {sc.description}")

    if goal.constraints:
        lines.append("\n## Constraints")
        for c in goal.constraints:
            lines.append(f"- {c.description}")

    spec = getattr(runtime, "_agent_spec", None)
    if spec and hasattr(spec, "tools") and spec.tools:
        lines.append(f"\n## Worker Tools\n{', '.join(sorted(spec.tools))}")

    lines.append("\nStatus at session start: idle (not started).")
    return "\n".join(lines)


# FLOWCHART_TYPES is imported from framework.tools.flowchart_utils


def _read_agent_triggers_json(agent_path: Path) -> list[dict]:
    """Read triggers.json from the agent's export directory."""
    triggers_path = agent_path / "triggers.json"
    if not triggers_path.exists():
        return []
    try:
        data = json.loads(triggers_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_agent_triggers_json(agent_path: Path, triggers: list[dict]) -> None:
    """Write triggers.json to the agent's export directory."""
    triggers_path = agent_path / "triggers.json"
    triggers_path.write_text(
        json.dumps(triggers, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _save_trigger_to_agent(session: Any, trigger_id: str, tdef: Any) -> None:
    """Persist a trigger definition to the agent's triggers.json."""
    agent_path = getattr(session, "worker_path", None)
    if agent_path is None:
        return
    triggers = _read_agent_triggers_json(agent_path)
    triggers = [t for t in triggers if t.get("id") != trigger_id]
    triggers.append(
        {
            "id": tdef.id,
            "name": tdef.description or tdef.id,
            "trigger_type": tdef.trigger_type,
            "trigger_config": tdef.trigger_config,
            "task": tdef.task or "",
        }
    )
    _write_agent_triggers_json(agent_path, triggers)
    logger.info("Saved trigger '%s' to %s/triggers.json", trigger_id, agent_path)


def _remove_trigger_from_agent(session: Any, trigger_id: str) -> None:
    """Remove a trigger definition from the agent's triggers.json."""
    agent_path = getattr(session, "worker_path", None)
    if agent_path is None:
        return
    triggers = _read_agent_triggers_json(agent_path)
    updated = [t for t in triggers if t.get("id") != trigger_id]
    if len(updated) != len(triggers):
        _write_agent_triggers_json(agent_path, updated)
        logger.info("Removed trigger '%s' from %s/triggers.json", trigger_id, agent_path)


async def _persist_active_triggers(session: Any, session_id: str) -> None:
    """Persist the set of active trigger IDs (and their tasks) to SessionState."""
    runtime = getattr(session, "colony_runtime", None)
    if runtime is None:
        return
    store = getattr(runtime, "_session_store", None)
    if store is None:
        return
    try:
        state = await store.read_state(session_id)
        if state is None:
            return
        active_ids = list(getattr(session, "active_trigger_ids", set()))
        state.active_triggers = active_ids
        # Persist per-trigger task overrides
        available = getattr(session, "available_triggers", {})
        state.trigger_tasks = {
            tid: available[tid].task for tid in active_ids if tid in available and available[tid].task
        }
        await store.write_state(session_id, state)
    except Exception:
        logger.warning("Failed to persist active triggers for session %s", session_id, exc_info=True)


async def _start_trigger_timer(session: Any, trigger_id: str, tdef: Any) -> None:
    """Start an asyncio background task that fires the trigger on a timer."""
    from framework.agent_loop.agent_loop import TriggerEvent

    cron_expr = tdef.trigger_config.get("cron")
    interval_minutes = tdef.trigger_config.get("interval_minutes")

    async def _timer_loop() -> None:
        if cron_expr:
            from croniter import croniter

            cron = croniter(cron_expr, datetime.now(tz=UTC))

        while True:
            try:
                if cron_expr:
                    next_fire = cron.get_next(datetime)
                    delay = (next_fire - datetime.now(tz=UTC)).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(float(interval_minutes) * 60)

                # Record next fire time for introspection (monotonic, matches routes)
                fire_times = getattr(session, "trigger_next_fire", None)
                if fire_times is not None:
                    _next_delay = float(interval_minutes) * 60 if interval_minutes else 60
                    fire_times[trigger_id] = time.monotonic() + _next_delay

                # Gate on a graph being loaded
                if getattr(session, "colony_runtime", None) is None:
                    continue

                # Fire into queen node
                executor = getattr(session, "queen_executor", None)
                if executor is None:
                    continue
                queen_node = getattr(executor, "node_registry", {}).get("queen")
                if queen_node is None:
                    continue

                event = TriggerEvent(
                    trigger_type="timer",
                    source_id=trigger_id,
                    payload={
                        "task": tdef.task or "",
                        "trigger_config": tdef.trigger_config,
                    },
                )
                await queen_node.inject_trigger(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Timer trigger '%s' tick failed", trigger_id, exc_info=True)

    task = asyncio.create_task(_timer_loop(), name=f"trigger_timer_{trigger_id}")
    if not hasattr(session, "active_timer_tasks"):
        session.active_timer_tasks = {}
    session.active_timer_tasks[trigger_id] = task


async def _start_trigger_webhook(session: Any, trigger_id: str, tdef: Any) -> None:
    """Subscribe to WEBHOOK_RECEIVED events and route matching ones to the queen."""
    from framework.agent_loop.agent_loop import TriggerEvent
    from framework.host.webhook_server import WebhookRoute, WebhookServer, WebhookServerConfig

    bus = session.event_bus
    path = tdef.trigger_config.get("path", "")
    methods = [m.upper() for m in tdef.trigger_config.get("methods", ["POST"])]

    async def _on_webhook(event: AgentEvent) -> None:
        data = event.data or {}
        if data.get("path") != path:
            return
        if data.get("method", "").upper() not in methods:
            return
        # Gate on a graph being loaded
        if getattr(session, "colony_runtime", None) is None:
            return
        executor = getattr(session, "queen_executor", None)
        if executor is None:
            return
        queen_node = getattr(executor, "node_registry", {}).get("queen")
        if queen_node is None:
            return

        trigger_event = TriggerEvent(
            trigger_type="webhook",
            source_id=trigger_id,
            payload={
                "task": tdef.task or "",
                "path": data.get("path", ""),
                "method": data.get("method", ""),
                "headers": data.get("headers", {}),
                "payload": data.get("payload", {}),
                "query_params": data.get("query_params", {}),
            },
        )
        await queen_node.inject_trigger(trigger_event)

    sub_id = bus.subscribe(
        event_types=[EventType.WEBHOOK_RECEIVED],
        handler=_on_webhook,
        filter_stream=trigger_id,
    )
    if not hasattr(session, "active_webhook_subs"):
        session.active_webhook_subs = {}
    session.active_webhook_subs[trigger_id] = sub_id

    # Ensure the webhook HTTP server is running
    if getattr(session, "queen_webhook_server", None) is None:
        port = int(tdef.trigger_config.get("port", 8090))
        config = WebhookServerConfig(host="127.0.0.1", port=port)
        server = WebhookServer(bus, config)
        session.queen_webhook_server = server

    server = session.queen_webhook_server
    route = WebhookRoute(source_id=trigger_id, path=path, methods=methods)
    server.add_route(route)
    if not getattr(server, "is_running", False):
        await server.start()
        server.is_running = True

def _update_meta_json(session_manager, manager_session_id, updates: dict) -> None:
    """Merge updates into the queen session's meta.json."""
    if session_manager is None or not manager_session_id:
        return
    srv_session = session_manager.get_session(manager_session_id)
    if not srv_session:
        return
    from framework.config import QUEENS_DIR

    storage_sid = getattr(srv_session, "queen_resume_from", None) or srv_session.id
    queen_name = getattr(srv_session, "queen_name", "default")
    meta_path = QUEENS_DIR / queen_name / "sessions" / storage_sid / "meta.json"
    try:
        existing = {}
        if meta_path.exists():
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        existing.update(updates)
        meta_path.write_text(json.dumps(existing), encoding="utf-8")
    except OSError:
        pass


def register_queen_lifecycle_tools(
    registry: ToolRegistry,
    session: Any = None,
    session_id: str | None = None,
    # Legacy params — used by TUI when not passing a session object
    colony_runtime: ColonyRuntime | None = None,
    event_bus: EventBus | None = None,
    storage_path: Path | None = None,
    # Server context — enables load_built_agent tool
    session_manager: Any = None,
    manager_session_id: str | None = None,
    # Mode switching
    phase_state: QueenPhaseState | None = None,
) -> int:
    """Register queen lifecycle tools.

    Args:
        session: A Session or WorkerSessionAdapter with ``colony_runtime``
            attribute. The tools read ``session.colony_runtime`` on each
            call, supporting late-binding.
        session_id: Shared session ID so the colony uses the same session
            scope as the queen and judge.
        colony_runtime: (Legacy) Direct runtime reference. If ``session``
            is not provided, a WorkerSessionAdapter is created from
            colony_runtime + event_bus + storage_path.
        session_manager: (Server only) The SessionManager instance, needed
            for ``load_built_agent`` to hot-load a colony.
        manager_session_id: (Server only) The session's ID in the manager.
        phase_state: (Optional) Mutable phase state for working/reviewing
            phase switching.

    Returns the number of tools registered.
    """
    # Build session adapter from legacy params if needed
    if session is None:
        if colony_runtime is None:
            raise ValueError("Either session or colony_runtime must be provided")
        session = WorkerSessionAdapter(
            colony_runtime=colony_runtime,
            event_bus=event_bus,
            worker_path=storage_path,
        )

    from framework.llm.provider import Tool

    tools_registered = 0

    def _get_runtime():
        """Get current colony runtime from session (late-binding)."""
        return getattr(session, "colony_runtime", None)

    # ``start_worker`` was removed in the Phase 4 unification — its
    # bare-bones spawn duplicated ``run_agent_with_input`` (which has
    # credential preflight, concurrency guard, and phase tracking on
    # top). The shared preflight timeout below is used by both
    # ``run_agent_with_input`` and ``run_parallel_workers``.
    _START_PREFLIGHT_TIMEOUT = 15  # seconds

    async def _preflight_credentials(
        legacy: Any,
        *,
        tool_label: str,
    ) -> set[str]:
        """Compute tools whose credentials are missing and resync MCP servers.

        Shared between ``run_agent_with_input`` (single spawn) and
        ``run_parallel_workers`` (batch spawn). Returns the set of
        tool names whose credentials failed validation; the caller
        filters these out of the spawn's tool lists.

        Exceptions (including validator bugs) are logged and treated
        as "no tools dropped" so a broken validator can't block a
        spawn. Wall-clock bound at ``_START_PREFLIGHT_TIMEOUT`` —
        slow credential HTTP health checks can't stall the LLM turn.
        """
        unavailable: set[str] = set()

        async def _run() -> None:
            nonlocal unavailable
            try:
                from framework.credentials.validation import compute_unavailable_tools

                loop = asyncio.get_running_loop()
                drop, messages = await loop.run_in_executor(
                    None,
                    lambda: compute_unavailable_tools(legacy.graph.nodes),
                )
                unavailable = drop
                if drop:
                    logger.warning(
                        "%s: dropping %d tool(s) with unavailable credentials: %s",
                        tool_label,
                        len(drop),
                        "; ".join(messages),
                    )
            except Exception as exc:
                logger.warning(
                    "%s: compute_unavailable_tools raised, proceeding without "
                    "credential-based tool filtering: %s",
                    tool_label,
                    exc,
                )

            runner = getattr(session, "runner", None)
            if runner is not None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: runner._tool_registry.resync_mcp_servers_if_needed(),
                    )
                except Exception as exc:
                    logger.warning("%s: MCP resync failed: %s", tool_label, exc)

        try:
            await asyncio.wait_for(_run(), timeout=_START_PREFLIGHT_TIMEOUT)
        except TimeoutError:
            logger.warning(
                "%s: credential preflight timed out after %ds — proceeding",
                tool_label,
                _START_PREFLIGHT_TIMEOUT,
            )
        return unavailable

    # --- stop_worker -----------------------------------------------------------

    async def stop_worker(*, reason: str = "Stopped by queen") -> str:
        """Stop all active workers in the session.

        Stops workers on BOTH the unified ColonyRuntime (``session.colony``
        — where ``run_agent_with_input`` and ``run_parallel_workers``
        spawn) AND the legacy ``session.colony_runtime`` (loaded
        AgentHost — still tracks timers and any legacy triggers). A
        previous version only stopped the legacy runtime, which meant
        workers spawned via the new path kept running silently after
        the queen called this tool.
        """
        stopped_unified = 0
        stopped_legacy = 0
        errors: list[str] = []

        # 1. Stop everything on the unified ColonyRuntime. This is
        # where run_agent_with_input and run_parallel_workers live.
        colony = getattr(session, "colony", None)
        if colony is not None:
            try:
                # Count live workers BEFORE stopping so we can report
                # accurately — stop_all_workers clears the dict.
                stopped_unified = sum(1 for w in colony.list_workers() if w.status.value in ("pending", "running"))
                await colony.stop_all_workers()
            except Exception as e:
                errors.append(f"unified: {e}")
                logger.warning(
                    "stop_worker: failed to stop unified colony workers",
                    exc_info=True,
                )

        # 2. Stop the legacy runtime too (timers, old-path workers).
        legacy = _get_runtime()
        if legacy is not None:
            try:
                legacy_workers = legacy.list_workers()
                stopped_legacy = len(legacy_workers) if isinstance(legacy_workers, list) else 0
                await legacy.stop_all_workers()
                legacy.pause_timers()
            except Exception as e:
                errors.append(f"legacy: {e}")
                logger.warning(
                    "stop_worker: failed to stop legacy runtime workers",
                    exc_info=True,
                )

        if colony is None and legacy is None:
            return json.dumps({"error": "No runtime on this session."})

        total_stopped = stopped_unified + stopped_legacy
        logger.info(
            "stop_worker: stopped %d workers (unified=%d, legacy=%d). reason=%s",
            total_stopped,
            stopped_unified,
            stopped_legacy,
            reason,
        )

        return json.dumps(
            {
                "status": "stopped",
                "workers_stopped": total_stopped,
                "unified_stopped": stopped_unified,
                "legacy_stopped": stopped_legacy,
                "timers_paused": legacy is not None,
                "reason": reason,
                "errors": errors if errors else None,
            }
        )

    _stop_tool = Tool(
        name="stop_worker",
        description=(
            "Cancel all active colony workers and pause timers. Workers stop gracefully. No parameters needed."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("stop_worker", _stop_tool, lambda inputs: stop_worker())
    tools_registered += 1

    # --- run_parallel_workers --------------------------------------------------
    #
    # Fire-and-forget fan-out tool. Spawns one Worker per task spec via
    # ``colony.spawn_batch`` and returns IMMEDIATELY with the worker ids
    # and schedule info. The tool no longer blocks on
    # ``wait_for_worker_reports`` — workers run in the background and
    # each emits a ``SUBAGENT_REPORT`` event when it terminates.
    # ``queen_orchestrator._on_worker_report`` subscribes to that event
    # and injects a ``[WORKER_REPORT]`` user turn into the queen's
    # conversation, so the queen sees each result as a normal inbound
    # message and can react without being blocked by the spawn call.
    #
    # Soft + hard timeouts are enforced by
    # ``ColonyRuntime.watch_batch_timeouts``: at soft-timeout, every
    # still-active worker that hasn't already filed an explicit report
    # receives a SOFT TIMEOUT inject telling it to call report_to_parent
    # now; at hard-timeout, any remaining worker is force-stopped
    # (and its SUBAGENT_REPORT still fires — explicit reports set right
    # before the stop are preserved).

    _RUN_PARALLEL_DEFAULT_TIMEOUT = 600.0       # soft timeout (10 min)
    _RUN_PARALLEL_HARD_TIMEOUT_CAP = 3600.0     # absolute safety-net cap (1 hour)

    def _compute_hard_timeout(soft: float) -> float:
        """Default hard cutoff: max(4× soft, soft + 600), capped at 3600s."""
        return min(
            _RUN_PARALLEL_HARD_TIMEOUT_CAP,
            max(soft * 4.0, soft + 600.0),
        )

    def _get_unified_colony():
        """Read the unified ColonyRuntime (Phase 2 wiring) from session."""
        return getattr(session, "colony", None)

    async def run_parallel_workers(
        *,
        tasks: list[dict],
        timeout: float | None = None,
        hard_timeout: float | None = None,
    ) -> str:
        """Spawn N parallel workers and return immediately.

        Each task is a dict ``{"task": str, "data": dict | None}``.
        Workers run in the background; each one emits a ``SUBAGENT_REPORT``
        when it finishes, which the queen sees as a ``[WORKER_REPORT]``
        user turn. The queen stays unblocked for other work.

        ``timeout`` is a **soft** deadline (default 600s). When it
        expires, each still-active worker without an explicit report
        gets a SOFT TIMEOUT inject telling it to call ``report_to_parent``
        now. Workers ignoring the warning are force-stopped at the
        ``hard_timeout`` (default: derived from ``timeout``, capped at
        3600s).
        """
        colony = _get_unified_colony()
        if colony is None:
            return json.dumps(
                {
                    "error": (
                        "No unified ColonyRuntime on this session. "
                        "Phase 2 wiring expects session.colony to be set "
                        "by SessionManager._start_unified_colony_runtime."
                    )
                }
            )

        if not isinstance(tasks, list) or not tasks:
            return json.dumps({"error": "tasks must be a non-empty list of {task, data?} dicts"})

        # Hard ceiling on a single fan-out call. A runaway queen requesting
        # thousands of parallel workers would starve memory and drown the
        # event loop; reject early with a clear error instead.
        # Laptop-safe default (8); override via HIVE_RUN_PARALLEL_HARD_CAP.
        _RUN_PARALLEL_HARD_CAP = 8
        _cap_env = os.environ.get("HIVE_RUN_PARALLEL_HARD_CAP")
        if _cap_env:
            try:
                _parsed = int(_cap_env)
                if _parsed > 0:
                    _RUN_PARALLEL_HARD_CAP = _parsed
            except ValueError:
                logger.warning(
                    "Invalid HIVE_RUN_PARALLEL_HARD_CAP=%r; using default %d",
                    _cap_env,
                    _RUN_PARALLEL_HARD_CAP,
                )
        if len(tasks) > _RUN_PARALLEL_HARD_CAP:
            return json.dumps(
                {
                    "error": (
                        f"run_parallel_workers received {len(tasks)} tasks, "
                        f"hard cap is {_RUN_PARALLEL_HARD_CAP}. Split the work "
                        "into sequential batches or tighten the task list."
                    )
                }
            )

        # Global concurrency enforcement against ColonyConfig.max_concurrent_workers.
        # The config field exists but was never checked anywhere — tracking
        # it here so recursive fan-outs can't silently exceed the budget.
        colony_cfg = getattr(colony, "_config", None) or getattr(colony, "config", None)
        max_concurrent = getattr(colony_cfg, "max_concurrent_workers", None)
        if max_concurrent and max_concurrent > 0:
            active = 0
            try:
                workers = getattr(colony, "_workers", {}) or {}
                for w in workers.values():
                    handle = getattr(w, "_task_handle", None)
                    if handle is not None and not handle.done():
                        active += 1
            except Exception:
                active = 0
            if active + len(tasks) > max_concurrent:
                return json.dumps(
                    {
                        "error": (
                            f"run_parallel_workers would exceed max_concurrent_workers "
                            f"({active} active + {len(tasks)} new > {max_concurrent}). "
                            "Wait for existing workers to finish or reduce batch size."
                        )
                    }
                )

        # Credential preflight — mirrors the one run_agent_with_input
        # performs. Without this, missing credentials (e.g. stale
        # GITHUB_TOKEN) fail once PER spawned worker, yielding N
        # duplicate error reports for a single fixable issue. Catch
        # once upfront, build a filtered tool list, and pass it to
        # every spawn via tools_override.
        legacy_for_preflight = _get_runtime()
        unavailable_tools_parallel: set[str] = set()
        tools_override_parallel: list[Any] | None = None
        if legacy_for_preflight is not None:
            try:
                unavailable_tools_parallel = await _preflight_credentials(
                    legacy_for_preflight, tool_label="run_parallel_workers"
                )
            except CredentialError as e:
                # Structured credential failure: publish the
                # CREDENTIALS_REQUIRED event so the frontend's modal
                # can fire, and return the same shape the single-path
                # tool returns on the same failure.
                error_payload = credential_errors_to_json(e)
                error_payload["agent_path"] = str(getattr(session, "worker_path", "") or "")
                bus = getattr(session, "event_bus", None)
                if bus is not None:
                    await bus.publish(
                        AgentEvent(
                            type=EventType.CREDENTIALS_REQUIRED,
                            stream_id="queen",
                            data=error_payload,
                        )
                    )
                return json.dumps(error_payload)

            # Always filter queen-lifecycle tools + any tools with missing
            # credentials. Without the queen-only strip the spawned worker
            # inherits run_parallel_workers / create_colony / switch_to_*,
            # which lets it recurse or flip the parent queen's phase.
            from framework.server.routes_execution import _resolve_queen_only_tools

            queen_only = _resolve_queen_only_tools()
            colony_tools = list(getattr(colony, "_tools", []) or [])
            before = len(colony_tools)
            tools_override_parallel = [
                t
                for t in colony_tools
                if getattr(t, "name", None) not in queen_only
                and getattr(t, "name", None) not in unavailable_tools_parallel
            ]
            dropped = before - len(tools_override_parallel)
            if dropped:
                logger.info(
                    "run_parallel_workers: stripped %d queen/unavailable tool(s) from spawn_tools",
                    dropped,
                )

        # Colony progress tracker wiring: if the session's loaded
        # worker points at a colony directory that has a progress.db,
        # inject db_path + colony_id into every per-task ``data``
        # dict so each spawned worker sees them in its first user
        # message and can claim rows from the queue. ColonyRuntime.
        # spawn() detects db_path in input_data and pre-activates
        # hive.colony-progress-tracker into the catalog prompt.
        _colony_db_path: str | None = None
        _colony_id: str | None = None
        _worker_path = getattr(session, "worker_path", None)
        if _worker_path:
            from pathlib import Path as _Path

            _wp = _Path(_worker_path)
            _pdb = _wp / "data" / "progress.db"
            if _pdb.exists():
                _colony_db_path = str(_pdb.resolve())
                _colony_id = _wp.name

        # Phase 2: enqueue each task into progress.db BEFORE building
        # spawn specs so every parallel worker has a pre-assigned row
        # to claim. Without this the queue stays empty and each
        # worker's claim UPDATE affects zero rows, silently falling
        # back to executing from its spawn message.
        _enqueued_task_ids: list[str | None] = [None] * len(tasks)
        if _colony_db_path:
            from pathlib import Path as _PathP

            from framework.host.progress_db import (
                enqueue_task as _enqueue_task_fn,
            )

            _pdb_path_obj = _PathP(_colony_db_path)
            for _i, _spec in enumerate(tasks):
                if not isinstance(_spec, dict):
                    continue
                _task_text_pre = str(_spec.get("task", "")).strip()
                if not _task_text_pre:
                    continue
                try:
                    _enqueued_task_ids[_i] = await asyncio.to_thread(
                        _enqueue_task_fn,
                        _pdb_path_obj,
                        _task_text_pre,
                        source="run_parallel_workers",
                    )
                except Exception as _enqueue_exc:
                    logger.warning(
                        "run_parallel_workers: failed to enqueue tasks[%d] "
                        "(spawn proceeding without pinned task_id): %s",
                        _i,
                        _enqueue_exc,
                    )

        # Normalise: each entry must have a non-empty "task" string.
        normalised: list[dict] = []
        for i, spec in enumerate(tasks):
            if not isinstance(spec, dict):
                return json.dumps({"error": f"tasks[{i}] is not a dict: {type(spec).__name__}"})
            task_text = str(spec.get("task", "")).strip()
            if not task_text:
                return json.dumps({"error": f"tasks[{i}].task is empty"})
            spec_data = spec.get("data") if isinstance(spec.get("data"), dict) else {}
            if _colony_db_path:
                spec_data = {
                    **spec_data,
                    "db_path": _colony_db_path,
                    "colony_id": _colony_id,
                }
                if _enqueued_task_ids[i]:
                    spec_data["task_id"] = _enqueued_task_ids[i]
            normalised.append(
                {
                    "task": task_text,
                    "data": spec_data or None,
                }
            )

        if _colony_db_path:
            _pinned = sum(1 for tid in _enqueued_task_ids if tid)
            logger.info(
                "run_parallel_workers: attached progress_db context to "
                "%d spawn(s) (colony_id=%s, %d pinned task_ids)",
                len(normalised),
                _colony_id,
                _pinned,
            )

        try:
            worker_ids = await colony.spawn_batch(
                normalised,
                tools_override=tools_override_parallel,
            )
        except Exception as e:
            return json.dumps({"error": f"spawn_batch failed: {e}"})

        # Phase transition — workers are now live, queen is in "working"
        # phase. Worker-finish auto-transitions back to "reviewing" once
        # every worker has reported (see queen_orchestrator._on_worker_report).
        if phase_state is not None:
            try:
                await phase_state.switch_to_working()
                _update_meta_json(
                    session_manager, manager_session_id, {"phase": "working"}
                )
            except Exception as exc:
                logger.warning(
                    "run_parallel_workers: phase transition to 'working' failed (non-fatal): %s",
                    exc,
                )

        # Soft + hard timeout watcher runs in the background. At soft,
        # it injects a "wrap up" message to every still-active worker
        # without an explicit report; at hard, it force-stops the stragglers.
        soft_timeout = timeout if timeout is not None else _RUN_PARALLEL_DEFAULT_TIMEOUT
        hard_timeout_effective = (
            hard_timeout if hard_timeout is not None else _compute_hard_timeout(soft_timeout)
        )
        if hard_timeout_effective <= soft_timeout:
            hard_timeout_effective = soft_timeout + 60.0  # enforce at least a 60s grace
        try:
            colony.watch_batch_timeouts(
                worker_ids,
                soft_timeout=soft_timeout,
                hard_timeout=hard_timeout_effective,
            )
        except Exception as exc:
            logger.warning(
                "run_parallel_workers: failed to schedule timeout watcher (non-fatal): %s",
                exc,
            )

        return json.dumps(
            {
                "status": "started",
                "worker_count": len(worker_ids),
                "worker_ids": worker_ids,
                "soft_timeout_seconds": soft_timeout,
                "hard_timeout_seconds": hard_timeout_effective,
                "message": (
                    "Workers running in the background. Each will report via "
                    "[WORKER_REPORT] as it finishes. Reply to the user naturally "
                    "in the meantime; you do not need to poll."
                ),
            }
        )

    _run_parallel_tool = Tool(
        name="run_parallel_workers",
        description=(
            "Fan out a batch of tasks to parallel workers and RETURN "
            "IMMEDIATELY. Workers run in the background; each one reports "
            "back to you as a [WORKER_REPORT] user turn when it finishes, "
            "so you stay unblocked and can chat with the user, kick off "
            "more work, or do anything else in the meantime.\n\n"
            "CRITICAL: each worker is a FRESH process with NO memory of "
            "your conversation. Every task string must be FULLY "
            "self-contained — include the API endpoint, the exact "
            "parameters, the expected output format, and any "
            "constraints. Workers cannot ask the user follow-up "
            "questions and cannot see your chat history. Write each "
            "task as if handing it to a stranger.\n\n"
            "Each worker runs in isolation with its own AgentLoop and "
            "reports back via the report_to_parent tool. The tool "
            "returns a JSON object with status='started' and the list "
            "of worker_ids you just spawned. Each worker's completion "
            "arrives later as a [WORKER_REPORT] message containing "
            "worker_id, status (success|partial|failed|timeout|stopped), "
            "summary, data, error, duration. Read those messages as "
            "they arrive and respond to the user naturally.\n\n"
            "TIMEOUT — 'timeout' is a SOFT deadline (default 600s). "
            "When it expires, every still-active worker that hasn't "
            "reported gets a [SOFT TIMEOUT] message telling it to "
            "call report_to_parent now. It has until 'hard_timeout' "
            "(default derived from timeout, capped at 3600s) to "
            "wrap up before being force-stopped. Explicit reports "
            "filed during the warning window ARE preserved."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of task specs to fan out. Each spec is "
                        '{"task": "<description>", "data": {<optional structured input>}}. '
                        "The 'task' string becomes the worker's initial "
                        "user message. 'data' is merged into the worker's "
                        "AgentContext.input_data so structured fields are "
                        "available to the worker's first turn."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "Task description for the worker.",
                            },
                            "data": {
                                "type": "object",
                                "description": "Optional structured input fields.",
                            },
                        },
                        "required": ["task"],
                    },
                    "minItems": 1,
                },
                "timeout": {
                    "type": "number",
                    "description": (
                        "SOFT deadline in seconds. Workers still running "
                        "at this point are messaged to call report_to_parent. "
                        "Default 600 (10 minutes)."
                    ),
                },
                "hard_timeout": {
                    "type": "number",
                    "description": (
                        "Absolute cutoff in seconds. Workers still active "
                        "at this point are force-stopped. Defaults to "
                        "max(timeout × 4, timeout + 600), capped at 3600s."
                    ),
                },
            },
            "required": ["tasks"],
        },
    )
    registry.register(
        "run_parallel_workers",
        _run_parallel_tool,
        lambda inputs: run_parallel_workers(**inputs),
    )
    tools_registered += 1

    # --- create_colony ---------------------------------------------------------
    #
    # Forks the current queen session into a colony. The queen passes
    # the skill content INLINE as tool arguments (skill_name,
    # skill_description, skill_body, and optional skill_files for
    # supporting scripts/references). The tool materializes the skill
    # folder under ``~/.hive/colonies/{colony_name}/.hive/skills/{name}/``
    # itself — colony-scoped, discovered as project scope by the
    # colony's worker and invisible to every other colony on the
    # machine — then forks.
    #
    # Why inline instead of a pre-authored folder path: earlier versions
    # required the queen to write SKILL.md with her own write_file tool
    # before calling create_colony. That leaked the harness's
    # read-before-write invariant onto a queen-owned artifact — if a
    # skill of the same name already existed the queen hit a generic
    # "refusing to overwrite" error and didn't know how to recover. By
    # inlining the content we make colony creation a single atomic
    # operation with domain-level semantics: the queen owns her skill
    # namespace inside the colony, so calling create_colony with an
    # existing name simply replaces the old skill (her latest content
    # wins).
    #
    # Why colony-scoped instead of user-scoped: an earlier version
    # materialized the folder at ``~/.hive/skills/{name}/``. That made
    # every colony on the machine see every colony-specific skill via
    # user-scope discovery — a worker in colony A could be offered
    # colony B's hyper-specific skill during selection. Writing into
    # the colony's own project dir kills that leak while still keeping
    # re-runs idempotent.

    import re as _re
    import shutil as _shutil

    _COLONY_NAME_RE = _re.compile(r"^[a-z0-9_]+$")
    _SKILL_NAME_RE = _re.compile(r"^[a-z0-9-]+$")

    def _materialize_skill_folder(
        *,
        skill_name: str,
        skill_description: str,
        skill_body: str,
        skill_files: list[dict] | None,
        colony_dir: Path,
    ) -> tuple[Path | None, str | None, bool]:
        """Write a skill folder under ``{colony_dir}/.hive/skills/{name}/`` from inline content.

        The skill is scoped to a single colony: ``SkillDiscovery`` scans
        ``{project_root}/.hive/skills/`` as project-scope, and the
        colony's worker uses ``project_root = colony_dir`` — so only
        that colony's workers see it, not every colony on the machine.
        We deliberately avoid ``~/.hive/skills/`` here because that
        directory is scanned as user scope and leaks into every agent.

        Returns ``(installed_path, error, replaced)``. On success
        ``error`` is ``None`` and ``installed_path`` is the final
        location; ``replaced`` is ``True`` when an existing skill with
        the same name was overwritten. On failure ``installed_path`` is
        ``None``, ``error`` is a human-readable reason, and
        ``replaced`` is ``False``.
        """
        name = (skill_name or "").strip() if isinstance(skill_name, str) else ""
        if not name:
            return None, "skill_name is required", False
        if not _SKILL_NAME_RE.match(name):
            return None, (f"skill_name '{name}' must match [a-z0-9-] pattern"), False
        if name.startswith("-") or name.endswith("-") or "--" in name:
            return None, (f"skill_name '{name}' has leading/trailing/consecutive hyphens"), False
        if len(name) > 64:
            return None, f"skill_name '{name}' exceeds 64 chars", False

        desc = (skill_description or "").strip() if isinstance(skill_description, str) else ""
        if not desc:
            return None, "skill_description is required", False
        if len(desc) > 1024:
            return None, "skill_description must be 1–1024 chars", False
        # Frontmatter descriptions must stay on a single line because
        # our frontmatter parser is line-oriented and the downstream
        # skill loader expects ``description:`` to resolve to one value.
        if "\n" in desc or "\r" in desc:
            return None, "skill_description must be a single line (no newlines)", False

        body = skill_body if isinstance(skill_body, str) else ""
        if not body.strip():
            return None, (
                "skill_body is required — the operational procedure the "
                "colony worker needs to run this job unattended"
            ), False

        # Optional supporting files (scripts/, references/, assets/…).
        # Each entry: {"path": "<relative>", "content": "<text>"}.
        normalized_files: list[tuple[Path, str]] = []
        if skill_files:
            if not isinstance(skill_files, list):
                return None, "skill_files must be an array", False
            for entry in skill_files:
                if not isinstance(entry, dict):
                    return None, "each skill_files entry must be an object with 'path' and 'content'", False
                rel_raw = entry.get("path")
                content = entry.get("content")
                if not isinstance(rel_raw, str) or not rel_raw.strip():
                    return None, "skill_files entry missing non-empty 'path'", False
                if not isinstance(content, str):
                    return None, f"skill_files entry '{rel_raw}' missing string 'content'", False
                rel_stripped = rel_raw.strip()
                # Normalize a leading ``./`` but do NOT strip bare ``/`` —
                # an absolute path should be rejected, not silently relativized.
                if rel_stripped.startswith("./"):
                    rel_stripped = rel_stripped[2:]
                rel_path = Path(rel_stripped)
                if (
                    rel_stripped.startswith("/")
                    or rel_path.is_absolute()
                    or ".." in rel_path.parts
                ):
                    return None, (
                        f"skill_files path '{rel_raw}' must be relative and inside the skill folder"
                    ), False
                if rel_path.as_posix() == "SKILL.md":
                    return None, (
                        "skill_files must not contain SKILL.md — pass skill_body instead"
                    ), False
                normalized_files.append((rel_path, content))

        target_root = colony_dir / ".hive" / "skills"
        target = target_root / name
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return None, f"failed to create skills root: {e}", False

        replaced = False
        try:
            if target.exists():
                # Queen is re-creating a skill under the same name —
                # her latest content wins. rmtree first so stale files
                # from a prior version don't linger alongside the new
                # ones (copytree with dirs_exist_ok would merge them).
                replaced = True
                _shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=False)

            body_norm = body.rstrip() + "\n"
            skill_md_text = (
                f"---\nname: {name}\ndescription: {desc}\n---\n\n{body_norm}"
            )
            (target / "SKILL.md").write_text(skill_md_text, encoding="utf-8")

            for rel_path, file_content in normalized_files:
                full_path = target / rel_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(file_content, encoding="utf-8")
        except OSError as e:
            return None, f"failed to write skill folder {target}: {e}", False

        return target, None, replaced

    async def create_colony(
        *,
        colony_name: str,
        task: str,
        skill_name: str,
        skill_description: str,
        skill_body: str,
        skill_files: list[dict] | None = None,
        tasks: list[dict] | None = None,
    ) -> str:
        """Create a colony and materialize its skill folder in one atomic call.

        The queen passes skill content inline: ``skill_name``,
        ``skill_description``, ``skill_body``, and optional
        ``skill_files`` (supporting scripts/references). The tool
        writes ``~/.hive/colonies/{colony_name}/.hive/skills/{skill_name}/``
        (colony-scoped, only this colony's workers see it), then forks
        the queen session into that colony directory and stores the
        task in ``worker.json``. NOTHING RUNS after fork.

        If a skill of the same name already exists inside this colony,
        it is overwritten — the queen owns her skill namespace inside
        the colony, and calling create_colony with an existing name
        means "my latest content wins."

        When *tasks* is provided, each entry is seeded into the
        colony's ``progress.db`` task queue in a single transaction.
        Workers then claim rows from the queue using the
        ``hive.colony-progress-tracker`` default skill. Each task dict
        accepts: ``goal`` (required), optional ``steps``,
        ``sop_items``, ``priority``, ``payload``, ``parent_task_id``.
        """
        if session is None:
            return json.dumps({"error": "No session bound to this tool registry."})

        cn = (colony_name or "").strip()
        if not _COLONY_NAME_RE.match(cn):
            return json.dumps(
                {"error": ("colony_name must be lowercase alphanumeric with underscores (e.g. 'honeycomb_research').")}
            )

        # Pre-create the colony dir so the skill can be materialized
        # INSIDE it (project scope, colony-local). fork_session_into_colony
        # keys "is_new" off worker.json rather than the dir itself, so
        # pre-creating here does not wrongly flag fresh colonies as "old".
        colony_dir = Path.home() / ".hive" / "colonies" / cn
        try:
            colony_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return json.dumps({"error": f"failed to create colony dir {colony_dir}: {e}"})

        installed_skill, skill_err, skill_replaced = _materialize_skill_folder(
            skill_name=skill_name,
            skill_description=skill_description,
            skill_body=skill_body,
            skill_files=skill_files,
            colony_dir=colony_dir,
        )
        if skill_err is not None:
            return json.dumps(
                {
                    "error": skill_err,
                    "hint": (
                        "Provide skill_name (lowercase [a-z0-9-], ≤64 chars), "
                        "skill_description (single line, 1–1024 chars), and "
                        "skill_body (the operational procedure the colony "
                        "worker needs to run unattended: API endpoints, "
                        "auth, gotchas, example requests, pre-baked "
                        "queries). Use skill_files for optional "
                        "scripts/references."
                    ),
                }
            )

        logger.info(
            "create_colony: materialized skill at %s (replaced=%s)",
            installed_skill,
            skill_replaced,
        )

        # Fork the queen session into the colony directory. The fork
        # copies conversations + writes worker.json + metadata.json.
        # NO worker runs after this call. The new colony's worker
        # inherits ~/.hive/skills/ on first run (whenever the user
        # actually starts it), so the freshly installed skill is
        # discoverable then.
        try:
            from framework.server.routes_execution import fork_session_into_colony
        except Exception as e:
            return json.dumps(
                {
                    "error": f"fork_session_into_colony import failed: {e}",
                    "skill_installed": str(installed_skill),
                }
            )

        try:
            fork_result = await fork_session_into_colony(
                session=session,
                colony_name=cn,
                task=(task or "").strip(),
                tasks=tasks if isinstance(tasks, list) else None,
            )
        except Exception as e:
            logger.exception("create_colony: fork failed after installing skill")
            return json.dumps(
                {
                    "error": f"colony fork failed: {e}",
                    "skill_installed": str(installed_skill),
                    "hint": (
                        "The skill was installed but the fork failed. "
                        "You can retry create_colony — re-installing "
                        "the skill is idempotent."
                    ),
                }
            )

        # Emit COLONY_CREATED so the frontend can render a system
        # message in the queen DM with a link to the new colony.
        # Without this the queen's text response is the only signal
        # the user gets, and there's no clickable navigation.
        bus = getattr(session, "event_bus", None)
        if bus is not None:
            try:
                await bus.publish(
                    AgentEvent(
                        type=EventType.COLONY_CREATED,
                        stream_id="queen",
                        data={
                            "colony_name": fork_result.get("colony_name", cn),
                            "colony_path": fork_result.get("colony_path"),
                            "queen_session_id": fork_result.get("queen_session_id"),
                            "is_new": fork_result.get("is_new", True),
                            "skill_installed": str(installed_skill),
                            "skill_name": installed_skill.name if installed_skill else None,
                            "skill_replaced": skill_replaced,
                            "task": (task or "").strip(),
                        },
                    )
                )
            except Exception:
                logger.warning(
                    "create_colony: failed to publish COLONY_CREATED event",
                    exc_info=True,
                )

        return json.dumps(
            {
                "status": "created",
                "colony_name": fork_result.get("colony_name", cn),
                "colony_path": fork_result.get("colony_path"),
                "queen_session_id": fork_result.get("queen_session_id"),
                "is_new": fork_result.get("is_new", True),
                "skill_installed": str(installed_skill),
                "skill_name": installed_skill.name if installed_skill else None,
                "skill_replaced": skill_replaced,
                "db_path": fork_result.get("db_path"),
                "tasks_seeded": len(fork_result.get("task_ids") or []),
            }
        )

    _create_colony_tool = Tool(
        name="create_colony",
        description=(
            "Fork this session into a persistent colony for work "
            "that needs to run HEADLESS, RECURRING, or IN PARALLEL "
            "to the current chat. Typical triggers: 'run this every "
            "morning / on a cron', 'keep monitoring X and alert me', "
            "'fire this off in the background so I can keep working "
            "here', 'spin up a dedicated agent for this job'. The "
            "criterion is operational — the work needs to keep "
            "running (or needs to survive this conversation ending). "
            "Do NOT use this just because you learned something "
            "reusable; if the user wants results right now in this "
            "chat, use run_parallel_workers instead.\n\n"
            "ATOMIC CALL: you pass the skill content INLINE as "
            "arguments (skill_name, skill_description, skill_body, "
            "optional skill_files). The tool writes the folder at "
            "~/.hive/colonies/{colony_name}/.hive/skills/{skill_name}/ "
            "— scoped to THIS colony only (project scope); no other "
            "colony on the machine can see it. Do NOT write the folder "
            "yourself with write_file; folders hand-authored at "
            "~/.hive/skills/ are user-scoped and LEAK to every colony. "
            "If a skill of the same name already exists under this "
            "colony, it is replaced by your latest content (you own "
            "your skill namespace inside the colony).\n\n"
            "NOTHING RUNS AFTER FORK. This tool is file-system only: "
            "it writes the skill folder, copies the queen session "
            "into a new colony directory, and stores the task in "
            "worker.json. No worker is started. The user navigates to "
            "the new colony when they're ready (or wires up a "
            "trigger); at that point the worker reads the task from "
            "worker.json and the skill from ~/.hive/skills/, and "
            "starts informed instead of clueless.\n\n"
            "WHY THE SKILL IS REQUIRED: a fresh worker running "
            "unattended has zero memory of your chat with the user. "
            "Whatever you figured out during this session — API auth "
            "flow, pagination, data shapes, gotchas, rate limits — "
            "must live in the skill, or the worker will repeat your "
            "discovery work every run.\n\n"
            "WHAT TO PUT IN THE SKILL BODY: the operational protocol "
            "the colony worker needs to do this work on its own. "
            "Include API endpoints with example requests, the exact "
            "auth flow, response shapes you observed, gotchas you hit "
            "(rate limits, pagination quirks, edge cases), "
            "conventions you settled on, and pre-baked "
            "queries/commands. Write it as if onboarding a new "
            "engineer who has never seen this system. Realistic "
            "target: 300–2000 chars of body. See your "
            "writing-hive-skills default skill for the spec."
        ),
        parameters={
            "type": "object",
            "properties": {
                "colony_name": {
                    "type": "string",
                    "description": (
                        "Lowercase alphanumeric+underscore name for the new colony (e.g. 'honeycomb_research')."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "FULL self-contained task description, baked "
                        "into worker.json for the colony's first run. "
                        "Nothing executes when create_colony returns — "
                        "the task is stored, not run. The user starts "
                        "the worker later from the new colony page. At "
                        "that point the worker has zero memory of your "
                        "chat, so this task string must contain "
                        "everything: every requirement, constraint, "
                        "and detail. Write it as if handing the work "
                        "to a stranger who has never seen the user's "
                        "request."
                    ),
                },
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Identifier for the skill folder. Lowercase "
                        "[a-z0-9-], no leading/trailing/consecutive "
                        "hyphens, ≤64 chars. Becomes the directory "
                        "under ~/.hive/colonies/<colony_name>/.hive/"
                        "skills/ and the frontmatter 'name' field. "
                        "Example: 'honeycomb-api-protocol'. Reusing "
                        "an existing name within this colony replaces "
                        "that skill."
                    ),
                },
                "skill_description": {
                    "type": "string",
                    "description": (
                        "One-line summary of when the skill applies, "
                        "1–1024 chars, no newlines. Becomes the "
                        "frontmatter 'description' field that drives "
                        "skill discovery. Example: 'How to query the "
                        "HoneyComb staging API for ticker, pool, and "
                        "trade data. Covers auth, pagination, pool "
                        "detail shape. Use when fetching market "
                        "data.'"
                    ),
                },
                "skill_body": {
                    "type": "string",
                    "description": (
                        "Markdown body of SKILL.md — the operational "
                        "procedure the colony worker needs to run "
                        "unattended. API endpoints with example "
                        "requests, auth flow, response shapes, "
                        "gotchas, pre-baked queries/commands. "
                        "300–2000 chars is the realistic target. Do "
                        "NOT include the '---' frontmatter markers; "
                        "the tool wraps your body with frontmatter "
                        "built from skill_name and skill_description."
                    ),
                },
                "skill_files": {
                    "type": "array",
                    "description": (
                        "Optional supporting files for the skill "
                        "folder (e.g. scripts/, references/, "
                        "assets/). Each entry is {path, content}: "
                        "'path' is a RELATIVE path inside the skill "
                        "folder (no leading slash, no '..', not "
                        "SKILL.md); 'content' is the file text. Use "
                        "this when the worker needs a runnable "
                        "script, a long reference document, or a "
                        "fixture alongside SKILL.md."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
                "tasks": {
                    "type": "array",
                    "description": (
                        "Optional pre-seeded task queue for the colony. "
                        "When the colony is a fan-out of many similar "
                        "units of work (e.g. 'process record #1234', "
                        "'scrape profile X'), pass them here as an "
                        "array and workers will claim rows atomically "
                        "from the SQLite queue using the "
                        "hive.colony-progress-tracker skill. Each task "
                        "needs a 'goal' string; optionally include "
                        "'steps' (ordered subtasks), 'sop_items' "
                        "(required checklist gates), 'priority' "
                        "(higher runs first), and 'payload' "
                        "(task-specific parameters). Can be hundreds "
                        "or thousands of entries — the bulk insert "
                        "runs in a single transaction."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string"},
                            "priority": {"type": "integer"},
                            "payload": {},
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "detail": {"type": "string"},
                                    },
                                    "required": ["title"],
                                },
                            },
                            "sop_items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string"},
                                        "description": {"type": "string"},
                                        "required": {"type": "boolean"},
                                    },
                                    "required": ["key", "description"],
                                },
                            },
                        },
                        "required": ["goal"],
                    },
                },
            },
            "required": [
                "colony_name",
                "task",
                "skill_name",
                "skill_description",
                "skill_body",
            ],
        },
    )
    registry.register(
        "create_colony",
        _create_colony_tool,
        lambda inputs: create_colony(**inputs),
    )
    tools_registered += 1

    # --- enqueue_task ------------------------------------------------------------

    async def enqueue_task_tool(
        *,
        colony_name: str,
        goal: str,
        steps: list[dict] | None = None,
        sop_items: list[dict] | None = None,
        payload: Any = None,
        priority: int = 0,
        parent_task_id: str | None = None,
    ) -> str:
        """Append a single task to an existing colony's progress.db queue.

        Use this when the colony is already created and more work
        needs to be fanned out (webhook-driven, follow-up requests,
        worker-generated subtasks). The colony's workers pick it up
        on their next claim cycle.
        """
        cn = (colony_name or "").strip()
        if not _COLONY_NAME_RE.match(cn):
            return json.dumps(
                {"error": "colony_name must be lowercase alphanumeric with underscores"}
            )

        from pathlib import Path as _Path

        from framework.host.progress_db import (
            enqueue_task as _enqueue_task,
            ensure_progress_db as _ensure_db,
        )

        colony_dir = _Path.home() / ".hive" / "colonies" / cn
        if not colony_dir.is_dir():
            return json.dumps({"error": f"colony '{cn}' not found"})

        try:
            db_path = await asyncio.to_thread(_ensure_db, colony_dir)
            task_id = await asyncio.to_thread(
                _enqueue_task,
                db_path,
                goal,
                steps=steps,
                sop_items=sop_items,
                payload=payload,
                priority=priority,
                parent_task_id=parent_task_id,
            )
        except Exception as e:
            logger.exception("enqueue_task: failed to insert row")
            return json.dumps({"error": f"enqueue_task failed: {e}"})

        return json.dumps(
            {
                "status": "enqueued",
                "colony_name": cn,
                "task_id": task_id,
                "db_path": str(db_path),
            }
        )

    _enqueue_task_tool = Tool(
        name="enqueue_task",
        description=(
            "Append a single task to an existing colony's progress.db "
            "queue. Use this after create_colony when more work needs "
            "to be fanned out — e.g. a webhook fired, the user asked "
            "for a follow-up run, or a worker spawned a subtask. The "
            "colony's workers pick it up on their next claim cycle "
            "(atomic UPDATE … WHERE status='pending'). For bulk "
            "authoring at colony creation time, pass the 'tasks' "
            "array to create_colony instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "colony_name": {
                    "type": "string",
                    "description": "Target colony name (lowercase + underscores).",
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "Human-readable task description. Self-contained — "
                        "the worker has no context beyond this string plus "
                        "any steps/sop_items/payload you attach."
                    ),
                },
                "steps": {
                    "type": "array",
                    "description": (
                        "Optional ordered subtasks the worker should "
                        "check off as it executes. Each step needs a "
                        "'title'; optional 'detail' for longer "
                        "instructions."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                },
                "sop_items": {
                    "type": "array",
                    "description": (
                        "Optional hard-gate checklist items the worker "
                        "MUST address before marking the task done. "
                        "Each item needs a 'key' (slug) and "
                        "'description'; 'required' defaults to true."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "description": {"type": "string"},
                            "required": {"type": "boolean"},
                        },
                        "required": ["key", "description"],
                    },
                },
                "payload": {
                    "description": (
                        "Optional task-specific parameters. Stored as "
                        "JSON in the 'payload' column."
                    ),
                },
                "priority": {
                    "type": "integer",
                    "description": "Higher values run first. Default 0.",
                },
                "parent_task_id": {
                    "type": "string",
                    "description": (
                        "Optional reference to an existing task this "
                        "one was spawned from (audit only; no blocking "
                        "dependency resolver today)."
                    ),
                },
            },
            "required": ["colony_name", "goal"],
        },
    )
    registry.register(
        "enqueue_task",
        _enqueue_task_tool,
        lambda inputs: enqueue_task_tool(**inputs),
    )
    tools_registered += 1

    # --- switch_to_reviewing ----------------------------------------------------

    async def switch_to_reviewing_tool() -> str:
        """Stop the worker and switch to editing phase for config tweaks.

        The worker stays loaded. You can re-run with different input,
        inject config adjustments, or escalate to building/planning.
        """
        stop_result = await stop_worker()

        if phase_state is not None:
            await phase_state.switch_to_reviewing()
            _update_meta_json(session_manager, manager_session_id, {"phase": "editing"})

        result = json.loads(stop_result)
        result["phase"] = "editing"
        result["message"] = (
            "Worker stopped. You are now in editing phase. "
            "You can re-run with run_agent_with_input(task), tweak config "
            "with inject_message, or escalate to building/planning."
        )
        return json.dumps(result)

    _switch_editing_tool = Tool(
        name="switch_to_reviewing",
        description=(
            "Stop the running worker and switch to editing phase. "
            "The worker stays loaded — you can tweak config and re-run. "
            "Use this when you want to adjust the worker without rebuilding."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "switch_to_reviewing",
        _switch_editing_tool,
        lambda inputs: switch_to_reviewing_tool(),
    )
    tools_registered += 1


    # --- get_worker_status -----------------------------------------------------

    def _get_event_bus():
        """Get the session's event bus for querying history."""
        return getattr(session, "event_bus", None)

    # Tiered cooldowns: summary is free, detail has short cooldown, full keeps 30s
    _COOLDOWN_FULL = 30.0
    _COOLDOWN_DETAIL = 10.0
    _status_last_called: dict[str, float] = {}  # tier -> monotonic time

    def _format_elapsed(seconds: float) -> str:
        """Format seconds as human-readable duration."""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, rem = divmod(s, 60)
        if m < 60:
            return f"{m}m {rem}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    def _format_time_ago(ts) -> str:
        """Format a datetime as relative time ago."""

        now = datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        delta = (now - ts).total_seconds()
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta / 60)}m ago"
        return f"{int(delta / 3600)}h ago"

    def _preview_value(value: Any, max_len: int = 120) -> str:
        """Format a memory value for display, truncating if needed."""
        if value is None:
            return "null (not yet set)"
        if isinstance(value, list):
            preview = str(value)[:max_len]
            return f"[{len(value)} items] {preview}"
        if isinstance(value, dict):
            preview = str(value)[:max_len]
            return f"{{{len(value)} keys}} {preview}"
        s = str(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s

    def _build_preamble(
        runtime: AgentHost,
    ) -> dict[str, Any]:
        """Build the lightweight preamble: status, node, elapsed, iteration.

        Always cheap to compute. Returns a dict with:
        - status: idle / running / waiting_for_input
        - current_node, current_iteration, elapsed_seconds (when applicable)
        - pending_question (when waiting)
        - _active_execs (internal, stripped before return)
        """

        colony_id = runtime.colony_id
        reg = runtime.get_worker_registration(colony_id)
        if reg is None:
            return {"status": "not_loaded"}

        preamble: dict[str, Any] = {}

        # Execution state
        active_execs = []
        for ep_id, stream in reg.streams.items():
            for exec_id in stream.active_execution_ids:
                exec_info: dict[str, Any] = {
                    "execution_id": exec_id,
                    "entry_point": ep_id,
                }
                ctx = stream.get_context(exec_id)
                if ctx:
                    elapsed = (datetime.now() - ctx.started_at).total_seconds()
                    exec_info["elapsed_seconds"] = round(elapsed, 1)
                active_execs.append(exec_info)
        preamble["_active_execs"] = active_execs

        if not active_execs:
            preamble["status"] = "idle"
        else:
            waiting_nodes = []
            for _ep_id, stream in reg.streams.items():
                waiting_nodes.extend(stream.get_waiting_nodes())
            preamble["status"] = "waiting_for_input" if waiting_nodes else "running"
            if active_execs:
                preamble["elapsed_seconds"] = active_execs[0].get("elapsed_seconds", 0)

        # Enrich with EventBus basics (cheap limit=1 queries)
        bus = _get_event_bus()
        if bus:
            if preamble["status"] == "waiting_for_input":
                input_events = bus.get_history(event_type=EventType.CLIENT_INPUT_REQUESTED, limit=1)
                if input_events:
                    prompt = input_events[0].data.get("prompt", "")
                    if prompt:
                        preamble["pending_question"] = prompt[:200]

            edge_events = bus.get_history(event_type=EventType.NODE_RETRY, limit=1)
            if edge_events:
                target = edge_events[0].data.get("target_node")
                if target:
                    preamble["current_node"] = target

            iter_events = bus.get_history(event_type=EventType.NODE_LOOP_ITERATION, limit=1)
            if iter_events:
                preamble["current_iteration"] = iter_events[0].data.get("iteration")

        return preamble

    def _detect_red_flags(bus: EventBus) -> int:
        """Count issue categories with cheap limit=1 queries."""
        count = 0
        for evt_type in (
            EventType.NODE_STALLED,
            EventType.NODE_TOOL_DOOM_LOOP,
            EventType.CONSTRAINT_VIOLATION,
        ):
            if bus.get_history(event_type=evt_type, limit=1):
                count += 1
        return count

    def _format_summary(preamble: dict[str, Any], red_flags: int) -> str:
        """Generate a 1-2 sentence prose summary from the preamble."""
        status = preamble["status"]

        if status == "idle":
            return "Worker is idle. No active executions."
        if status == "not_loaded":
            return "No worker loaded."
        if status == "waiting_for_input":
            q = preamble.get("pending_question", "")
            if q:
                return f'Worker is waiting for input: "{q}"'
            return "Worker is waiting for input."

        # Running
        parts = []
        elapsed = preamble.get("elapsed_seconds", 0)
        parts.append(f"Worker is running ({_format_elapsed(elapsed)})")

        node = preamble.get("current_node")
        iteration = preamble.get("current_iteration")
        if node:
            node_part = f"Currently in {node}"
            if iteration is not None:
                node_part += f", iteration {iteration}"
            parts.append(node_part)

        if red_flags:
            parts.append(f"{red_flags} issue type(s) detected — use focus='issues' for details")
        else:
            parts.append("No issues detected")

        # Latest subagent progress (if any delegation is in flight)
        bus = _get_event_bus()
        if bus:
            sa_reports = bus.get_history(event_type=EventType.SUBAGENT_REPORT, limit=1)
            if sa_reports:
                latest = sa_reports[0]
                sa_msg = str(latest.data.get("message", ""))[:200]
                ago = _format_time_ago(latest.timestamp)
                parts.append(f"Latest subagent update ({ago}): {sa_msg}")

        return ". ".join(parts) + "."

    def _format_activity(bus: EventBus, preamble: dict[str, Any], last_n: int) -> str:
        """Format current activity: node, iteration, transitions, LLM output."""
        lines = []

        node = preamble.get("current_node", "unknown")
        iteration = preamble.get("current_iteration")
        elapsed = preamble.get("elapsed_seconds", 0)
        node_desc = f"Current node: {node}"
        if iteration is not None:
            node_desc += f" (iteration {iteration}, {_format_elapsed(elapsed)} elapsed)"
        else:
            node_desc += f" ({_format_elapsed(elapsed)} elapsed)"
        lines.append(node_desc)

        # Latest LLM output snippet
        text_events = bus.get_history(event_type=EventType.LLM_TEXT_DELTA, limit=1)
        if text_events:
            snapshot = text_events[0].data.get("snapshot", "") or ""
            snippet = snapshot[-300:].strip()
            if snippet:
                # Show last meaningful chunk
                lines.append(f'Last LLM output: "{snippet}"')

        # Recent node transitions
        edges = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if edges:
            lines.append("")
            lines.append("Recent transitions:")
            for evt in edges:
                src = evt.data.get("source_node", "?")
                tgt = evt.data.get("target_node", "?")
                cond = evt.data.get("edge_condition", "")
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {src} -> {tgt} ({cond}, {ago})")

        return "\n".join(lines)

    async def _format_memory(runtime: AgentHost) -> str:
        """Format the worker's shared buffer snapshot and recent changes."""
        from framework.host.isolation import IsolationLevel

        lines = []
        active_streams = runtime.get_active_streams()

        if not active_streams:
            return "Worker has no active executions. No buffer state to inspect."

        # Read buffer state from the first active execution
        stream_info = active_streams[0]
        exec_ids = stream_info.get("active_execution_ids", [])
        stream_id = stream_info.get("stream_id", "")
        if not exec_ids:
            return "No active execution found."

        exec_id = exec_ids[0]
        buf = runtime.state_manager.create_buffer(exec_id, stream_id, IsolationLevel.SHARED)
        state = await buf.read_all()

        if not state:
            lines.append("Worker's shared buffer is empty.")
        else:
            lines.append(f"Worker's shared buffer ({len(state)} keys):")
            for key, value in state.items():
                lines.append(f"  {key}: {_preview_value(value)}")

        # Recent state changes
        changes = runtime.state_manager.get_recent_changes(limit=5)
        if changes:
            lines.append("")
            lines.append(f"Recent changes (last {len(changes)}):")
            for change in reversed(changes):  # most recent first
                from datetime import datetime

                ago = _format_time_ago(datetime.fromtimestamp(change.timestamp, tz=UTC))
                if change.old_value is None:
                    lines.append(f"  {change.key} set ({ago})")
                else:
                    old_preview = _preview_value(change.old_value, 40)
                    new_preview = _preview_value(change.new_value, 40)
                    lines.append(f"  {change.key}: {old_preview} -> {new_preview} ({ago})")

        return "\n".join(lines)

    def _format_tools(bus: EventBus, last_n: int) -> str:
        """Format running and recent tool calls."""
        lines = []

        # Running tools (started but not yet completed)
        tool_started = bus.get_history(event_type=EventType.TOOL_CALL_STARTED, limit=last_n * 2)
        tool_completed = bus.get_history(event_type=EventType.TOOL_CALL_COMPLETED, limit=last_n * 2)
        completed_ids = {evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")}
        running = [
            evt
            for evt in tool_started
            if evt.data.get("tool_use_id") and evt.data.get("tool_use_id") not in completed_ids
        ]

        if running:
            names = [evt.data.get("tool_name", "?") for evt in running]
            lines.append(f"{len(running)} tool(s) running: {', '.join(names)}.")
            for evt in running:
                name = evt.data.get("tool_name", "?")
                node = evt.node_id or "?"
                ago = _format_time_ago(evt.timestamp)
                inp = str(evt.data.get("tool_input", ""))[:150]
                lines.append(f"  {name} ({node}, started {ago})")
                if inp:
                    lines.append(f"    Input: {inp}")
        else:
            lines.append("No tools currently running.")

        # Recent completed calls
        if tool_completed:
            lines.append("")
            lines.append(f"Recent calls (last {min(last_n, len(tool_completed))}):")
            for evt in tool_completed[:last_n]:
                name = evt.data.get("tool_name", "?")
                node = evt.node_id or "?"
                is_error = bool(evt.data.get("is_error"))
                status = "error" if is_error else "ok"
                duration = evt.data.get("duration_s")
                dur_str = f", {duration:.1f}s" if duration else ""
                lines.append(f"  {name} ({node}) — {status}{dur_str}")
                result_text = evt.data.get("result", "")
                if result_text:
                    preview = str(result_text)[:300].replace("\n", " ")
                    lines.append(f"    Result: {preview}")
        else:
            lines.append("No recent tool calls.")

        return "\n".join(lines)

    def _format_issues(bus: EventBus) -> str:
        """Format retries, stalls, doom loops, and constraint violations."""
        lines = []
        total = 0

        # Retries
        retries = bus.get_history(event_type=EventType.NODE_RETRY, limit=20)
        if retries:
            total += len(retries)
            lines.append(f"{len(retries)} retry event(s):")
            for evt in retries[:5]:
                node = evt.node_id or "?"
                count = evt.data.get("retry_count", "?")
                error = evt.data.get("error", "")[:120]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} (attempt {count}, {ago}): {error}")

        # Stalls
        stalls = bus.get_history(event_type=EventType.NODE_STALLED, limit=5)
        if stalls:
            total += len(stalls)
            lines.append(f"{len(stalls)} stall(s):")
            for evt in stalls:
                node = evt.node_id or "?"
                reason = evt.data.get("reason", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} ({ago}): {reason}")

        # Doom loops
        doom_loops = bus.get_history(event_type=EventType.NODE_TOOL_DOOM_LOOP, limit=5)
        if doom_loops:
            total += len(doom_loops)
            lines.append(f"{len(doom_loops)} tool doom loop(s):")
            for evt in doom_loops:
                node = evt.node_id or "?"
                desc = evt.data.get("description", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} ({ago}): {desc}")

        # Constraint violations
        violations = bus.get_history(event_type=EventType.CONSTRAINT_VIOLATION, limit=5)
        if violations:
            total += len(violations)
            lines.append(f"{len(violations)} constraint violation(s):")
            for evt in violations:
                cid = evt.data.get("constraint_id", "?")
                desc = evt.data.get("description", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {cid} ({ago}): {desc}")

        if total == 0:
            return "No issues detected. No retries, stalls, or constraint violations."

        header = f"{total} issue(s) detected."
        return header + "\n\n" + "\n".join(lines)

    async def _format_progress(runtime: AgentHost, bus: EventBus) -> str:
        """Format goal progress, token consumption, and execution outcomes."""
        lines = []

        # Goal progress
        try:
            progress = await runtime.get_goal_progress()
            if progress:
                criteria = progress.get("criteria_status", {})
                if criteria:
                    met = sum(1 for c in criteria.values() if c.get("met"))
                    total_c = len(criteria)
                    lines.append(f"Goal: {met}/{total_c} criteria met.")
                    for cid, cdata in criteria.items():
                        marker = "met" if cdata.get("met") else "not met"
                        desc = cdata.get("description", cid)
                        evidence = cdata.get("evidence", [])
                        ev_str = f" — {evidence[0]}" if evidence else ""
                        lines.append(f"  [{marker}] {desc}{ev_str}")
                rec = progress.get("recommendation")
                if rec:
                    lines.append(f"Recommendation: {rec}.")
        except Exception:
            lines.append("Goal progress unavailable.")

        # Token summary
        llm_events = bus.get_history(event_type=EventType.LLM_TURN_COMPLETE, limit=200)
        if llm_events:
            total_in = sum(evt.data.get("input_tokens", 0) or 0 for evt in llm_events)
            total_out = sum(evt.data.get("output_tokens", 0) or 0 for evt in llm_events)
            total_tok = total_in + total_out
            lines.append("")
            lines.append(
                f"Tokens: {len(llm_events)} LLM turns, {total_tok:,} total ({total_in:,} in + {total_out:,} out)."
            )

        # Execution outcomes
        exec_completed = bus.get_history(event_type=EventType.EXECUTION_COMPLETED, limit=5)
        exec_failed = bus.get_history(event_type=EventType.EXECUTION_FAILED, limit=5)
        completed_n = len(exec_completed)
        failed_n = len(exec_failed)
        active_n = len(runtime.get_active_streams())
        lines.append(
            f"Executions: {completed_n} completed, {failed_n} failed" + (f" ({active_n} active)." if active_n else ".")
        )
        if exec_failed:
            for evt in exec_failed[:3]:
                error = evt.data.get("error", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  Failed ({ago}): {error}")

        return "\n".join(lines)

    def _build_full_json(
        runtime: AgentHost,
        bus: EventBus,
        preamble: dict[str, Any],
        last_n: int,
    ) -> dict[str, Any]:
        """Build the legacy full JSON response (backward compat for focus='full')."""

        colony_id = runtime.colony_id
        goal = runtime.goal
        result: dict[str, Any] = {
            "worker_colony_id": colony_id,
            "worker_goal": getattr(goal, "name", colony_id),
            "status": preamble["status"],
        }

        active_execs = preamble.get("_active_execs", [])
        if active_execs:
            result["active_executions"] = active_execs
        if preamble.get("pending_question"):
            result["pending_question"] = preamble["pending_question"]

        _idle = runtime.agent_idle_seconds
        result["agent_idle_seconds"] = round(_idle, 1) if _idle != float("inf") else -1

        for key in ("current_node", "current_iteration"):
            if key in preamble:
                result[key] = preamble[key]

        # Running + completed tool calls
        tool_started = bus.get_history(event_type=EventType.TOOL_CALL_STARTED, limit=last_n * 2)
        tool_completed = bus.get_history(event_type=EventType.TOOL_CALL_COMPLETED, limit=last_n * 2)
        completed_ids = {evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")}
        running = [
            evt
            for evt in tool_started
            if evt.data.get("tool_use_id") and evt.data.get("tool_use_id") not in completed_ids
        ]
        if running:
            result["running_tools"] = [
                {
                    "tool": evt.data.get("tool_name"),
                    "node": evt.node_id,
                    "started_at": evt.timestamp.isoformat(),
                    "input_preview": str(evt.data.get("tool_input", ""))[:200],
                }
                for evt in running
            ]
        if tool_completed:
            recent_calls = []
            for evt in tool_completed[:last_n]:
                entry: dict[str, Any] = {
                    "tool": evt.data.get("tool_name"),
                    "error": bool(evt.data.get("is_error")),
                    "node": evt.node_id,
                    "time": evt.timestamp.isoformat(),
                }
                result_text = evt.data.get("result", "")
                if result_text:
                    entry["result_preview"] = str(result_text)[:300]
                recent_calls.append(entry)
            result["recent_tool_calls"] = recent_calls

        # Node transitions
        edges = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if edges:
            result["node_transitions"] = [
                {
                    "from": evt.data.get("source_node"),
                    "to": evt.data.get("target_node"),
                    "condition": evt.data.get("edge_condition"),
                    "time": evt.timestamp.isoformat(),
                }
                for evt in edges
            ]

        # Retries
        retries = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if retries:
            result["retries"] = [
                {
                    "node": evt.node_id,
                    "retry_count": evt.data.get("retry_count"),
                    "error": evt.data.get("error", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in retries
            ]

        # Stalls and doom loops
        stalls = bus.get_history(event_type=EventType.NODE_STALLED, limit=5)
        doom_loops = bus.get_history(event_type=EventType.NODE_TOOL_DOOM_LOOP, limit=5)
        issues = []
        for evt in stalls:
            issues.append(
                {
                    "type": "stall",
                    "node": evt.node_id,
                    "reason": evt.data.get("reason", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
            )
        for evt in doom_loops:
            issues.append(
                {
                    "type": "tool_doom_loop",
                    "node": evt.node_id,
                    "description": evt.data.get("description", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
            )
        if issues:
            result["issues"] = issues

        # Subagent activity (in-flight progress from delegated subagents)
        sa_reports = bus.get_history(event_type=EventType.SUBAGENT_REPORT, limit=last_n)
        if sa_reports:
            result["subagent_activity"] = [
                {
                    "subagent": evt.data.get("subagent_id"),
                    "message": str(evt.data.get("message", ""))[:300],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in sa_reports[:last_n]
            ]

        # Constraint violations
        violations = bus.get_history(event_type=EventType.CONSTRAINT_VIOLATION, limit=5)
        if violations:
            result["constraint_violations"] = [
                {
                    "constraint": evt.data.get("constraint_id"),
                    "description": evt.data.get("description", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in violations
            ]

        # Token summary
        llm_events = bus.get_history(event_type=EventType.LLM_TURN_COMPLETE, limit=200)
        if llm_events:
            total_in = sum(evt.data.get("input_tokens", 0) or 0 for evt in llm_events)
            total_out = sum(evt.data.get("output_tokens", 0) or 0 for evt in llm_events)
            result["token_summary"] = {
                "llm_turns": len(llm_events),
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
            }

        # Execution outcomes
        exec_completed = bus.get_history(event_type=EventType.EXECUTION_COMPLETED, limit=5)
        exec_failed = bus.get_history(event_type=EventType.EXECUTION_FAILED, limit=5)
        if exec_completed or exec_failed:
            result["execution_outcomes"] = []
            for evt in exec_completed:
                result["execution_outcomes"].append(
                    {
                        "outcome": "completed",
                        "execution_id": evt.execution_id,
                        "time": evt.timestamp.isoformat(),
                    }
                )
            for evt in exec_failed:
                result["execution_outcomes"].append(
                    {
                        "outcome": "failed",
                        "execution_id": evt.execution_id,
                        "error": evt.data.get("error", "")[:200],
                        "time": evt.timestamp.isoformat(),
                    }
                )

        return result

    async def get_worker_status(focus: str | None = None, last_n: int = 20) -> str:
        """Check on the loaded graph with progressive disclosure.

        Without arguments, returns a brief prose summary. Use ``focus`` to
        drill into specifics: activity, memory, tools, issues, progress,
        or full (JSON dump).

        Args:
            focus: Aspect to inspect (activity/memory/tools/issues/progress/full).
                   Omit for a brief summary.
            last_n: Recent events per category (default 20). For activity, tools, full.
        """
        import time as _time

        # --- Tiered cooldown ---
        # summary is free, detail has 10s, full keeps 30s
        now = _time.monotonic()
        if focus == "full":
            cooldown = _COOLDOWN_FULL
            tier = "full"
        elif focus is None:
            cooldown = 0.0
            tier = "summary"
        else:
            cooldown = _COOLDOWN_DETAIL
            tier = "detail"

        elapsed_since = now - _status_last_called.get(tier, 0.0)
        if elapsed_since < cooldown:
            remaining = int(cooldown - elapsed_since)
            return json.dumps(
                {
                    "status": "cooldown",
                    "message": (
                        f"Status '{focus or 'summary'}' was checked {int(elapsed_since)}s ago. "
                        f"Wait {remaining}s or try a different focus."
                    ),
                }
            )
        _status_last_called[tier] = now

        # --- Runtime check ---
        runtime = _get_runtime()
        if runtime is None:
            return "No colony running."

        preamble = _build_preamble(runtime)

        bus = _get_event_bus()

        try:
            if focus is None:
                # Default: brief prose summary
                red_flags = _detect_red_flags(bus) if bus else 0
                return _format_summary(preamble, red_flags)

            if bus is None:
                return f"Worker is {preamble['status']}. EventBus unavailable — only basic status returned."

            if focus == "activity":
                return _format_activity(bus, preamble, last_n)
            elif focus == "memory":
                return await _format_memory(runtime)
            elif focus == "tools":
                return _format_tools(bus, last_n)
            elif focus == "issues":
                return _format_issues(bus)
            elif focus == "progress":
                return await _format_progress(runtime, bus)
            elif focus == "full":
                result = _build_full_json(runtime, bus, preamble, last_n)
                # Also include goal progress in full dump
                try:
                    progress = await runtime.get_goal_progress()
                    if progress:
                        result["goal_progress"] = progress
                except Exception:
                    pass
                return json.dumps(result, default=str, ensure_ascii=False)
            else:
                return f"Unknown focus '{focus}'. Valid options: activity, memory, tools, issues, progress, full."
        except Exception as exc:
            logger.exception("get_worker_status error")
            return f"Error retrieving status: {exc}"

    _status_tool = Tool(
        name="get_worker_status",
        description=(
            "Check on the loaded graph. Returns a brief prose summary by default. "
            "Use 'focus' to drill into specifics:\n"
            "- activity: current node, transitions, latest LLM output\n"
            "- memory: worker's accumulated buffer state\n"
            "- tools: running and recent tool calls\n"
            "- issues: retries, stalls, constraint violations\n"
            "- progress: goal criteria, token consumption\n"
            "- full: everything as JSON"
        ),
        parameters={
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": ["activity", "memory", "tools", "issues", "progress", "full"],
                    "description": ("Aspect to inspect. Omit for a brief summary."),
                },
                "last_n": {
                    "type": "integer",
                    "description": ("Recent events per category (default 20). Only for activity, tools, full."),
                },
            },
            "required": [],
        },
    )
    registry.register("get_worker_status", _status_tool, lambda inputs: get_worker_status(**inputs))
    tools_registered += 1

    # --- inject_message -------------------------------------------------------

    async def inject_message(content: str) -> str:
        """Send a message to the running graph.

        Injects the message into the worker's active node conversation.
        Use this to relay user instructions to the worker.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No colony running in this session."})

        colony_id = runtime.colony_id
        reg = runtime.get_worker_registration(colony_id)
        if reg is None:
            return json.dumps({"error": "Colony not found"})

        # Prefer nodes that are actively waiting (e.g. escalation receivers
        # blocked on queen guidance) over the main event-loop node.
        for stream in reg.streams.values():
            waiting = stream.get_waiting_nodes()
            if waiting:
                target_node_id = waiting[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content, is_client_input=True)
                if ok:
                    return json.dumps(
                        {
                            "status": "delivered",
                            "node_id": target_node_id,
                            "content_preview": content[:100],
                        }
                    )

        # Fallback: inject into any injectable node
        for stream in reg.streams.values():
            injectable = stream.get_injectable_nodes()
            if injectable:
                target_node_id = injectable[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content, is_client_input=True)
                if ok:
                    return json.dumps(
                        {
                            "status": "delivered",
                            "node_id": target_node_id,
                            "content_preview": content[:100],
                        }
                    )

        return json.dumps(
            {
                "error": "No active graph node found — graph may be idle.",
            }
        )

    _inject_tool = Tool(
        name="inject_message",
        description=(
            "Send a message to the running graph. The message is injected "
            "into the graph's active node conversation. Use this to relay user "
            "instructions or concerns. The graph must be running."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Message content to send to the graph",
                },
            },
            "required": ["content"],
        },
    )
    registry.register("inject_message", _inject_tool, lambda inputs: inject_message(**inputs))
    tools_registered += 1

    # --- list_credentials -----------------------------------------------------

    async def list_credentials(credential_id: str = "") -> str:
        """List all authorized credentials (Aden OAuth + local encrypted store).

        Returns credential IDs, aliases, status, and identity metadata.
        Never returns secret values. Optionally filter by credential_id.
        """
        # Load shell config vars into os.environ — same first step as check-agent.
        # Ensures keys set in ~/.zshrc/~/.bashrc are visible to is_available() checks.
        try:
            from framework.credentials.validation import ensure_credential_key_env

            ensure_credential_key_env()
        except Exception:
            pass

        try:
            # Primary: CredentialStoreAdapter sees both Aden OAuth and local accounts
            from aden_tools.credentials import CredentialStoreAdapter

            store = CredentialStoreAdapter.default()
            all_accounts = store.get_all_account_info()

            # Filter by credential_id / provider if requested.
            # A spec name like "gmail_oauth" maps to provider "google" via
            # credential_id field — resolve that alias before filtering.
            if credential_id:
                try:
                    from aden_tools.credentials import CREDENTIAL_SPECS

                    spec = CREDENTIAL_SPECS.get(credential_id)
                    resolved_provider = (spec.credential_id or credential_id) if spec else credential_id
                except Exception:
                    resolved_provider = credential_id
                all_accounts = [
                    a
                    for a in all_accounts
                    if a.get("credential_id", "").startswith(credential_id)
                    or a.get("provider", "") in (credential_id, resolved_provider)
                ]

            return json.dumps(
                {
                    "count": len(all_accounts),
                    "credentials": all_accounts,
                },
                default=str,
            )
        except ImportError:
            pass
        except Exception as e:
            return json.dumps({"error": f"Failed to list credentials: {e}"})

        # Fallback: local encrypted store only
        try:
            from framework.credentials.local.models import LocalAccountInfo
            from framework.credentials.local.registry import LocalCredentialRegistry
            from framework.credentials.storage import EncryptedFileStorage

            registry = LocalCredentialRegistry.default()
            accounts = registry.list_accounts(
                credential_id=credential_id or None,
            )

            # Also include flat-file credentials saved by the GUI (no "/" separator).
            # LocalCredentialRegistry.list_accounts() skips these — read them directly.
            seen_cred_ids = {info.credential_id for info in accounts}
            storage = EncryptedFileStorage()
            for storage_id in storage.list_all():
                if "/" in storage_id:
                    continue  # already handled by LocalCredentialRegistry above
                if credential_id and storage_id != credential_id:
                    continue
                if storage_id in seen_cred_ids:
                    continue
                try:
                    cred_obj = storage.load(storage_id)
                except Exception:
                    continue
                if cred_obj is None:
                    continue
                accounts.append(
                    LocalAccountInfo(
                        credential_id=storage_id,
                        alias="default",
                        status="unknown",
                        identity=cred_obj.identity,
                        last_validated=cred_obj.last_refreshed,
                        created_at=cred_obj.created_at,
                    )
                )

            credentials = []
            for info in accounts:
                entry: dict[str, Any] = {
                    "credential_id": info.credential_id,
                    "alias": info.alias,
                    "storage_id": info.storage_id,
                    "status": info.status,
                    "created_at": info.created_at.isoformat() if info.created_at else None,
                    "last_validated": (info.last_validated.isoformat() if info.last_validated else None),
                }
                identity = info.identity.to_dict()
                if identity:
                    entry["identity"] = identity
                credentials.append(entry)

            return json.dumps(
                {
                    "count": len(credentials),
                    "credentials": credentials,
                    "location": "~/.hive/credentials",
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to list credentials: {e}"})

    _list_creds_tool = Tool(
        name="list_credentials",
        description=(
            "List all authorized credentials in the local store. Returns credential IDs, "
            "aliases, status (active/failed/unknown), and identity metadata — never secret "
            "values. Optionally filter by credential_id (e.g. 'brave_search')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "credential_id": {
                    "type": "string",
                    "description": (
                        "Filter to a specific credential type (e.g. 'brave_search'). Omit to list all credentials."
                    ),
                },
            },
            "required": [],
        },
    )
    registry.register("list_credentials", _list_creds_tool, lambda inputs: list_credentials(**inputs))
    tools_registered += 1

    # --- list_worker_questions / reply_to_worker ------------------------------
    #
    # Workers escalate via the framework-level ``escalate`` tool, which emits
    # ESCALATION_REQUESTED events stamped with a fresh request_id. The queen's
    # colony-scoped subscription (see queen_orchestrator._on_worker_escalation)
    # records each pending escalation on ``session.pending_escalations``,
    # keyed by request_id, so multiple concurrent waiters stay addressable.
    # These tools read and drain that inbox.

    async def list_worker_questions() -> str:
        """List pending worker escalations awaiting a queen reply."""
        pending = getattr(session, "pending_escalations", None) or {}
        # Copy values and trim context to keep the tool return compact.
        entries = []
        now = time.time()
        for entry in pending.values():
            entries.append(
                {
                    "request_id": entry.get("request_id"),
                    "worker_id": entry.get("worker_id"),
                    "colony_id": entry.get("colony_id"),
                    "node_id": entry.get("node_id"),
                    "reason": entry.get("reason"),
                    "context_preview": (entry.get("context") or "")[:300],
                    "waiting_seconds": round(now - float(entry.get("opened_at") or now), 1),
                }
            )
        return json.dumps({"count": len(entries), "pending": entries})

    _list_questions_tool = Tool(
        name="list_worker_questions",
        description=(
            "List all worker escalations currently awaiting your reply. "
            "Each entry has a request_id that you pass to reply_to_worker() "
            "to unblock the specific worker that asked."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "list_worker_questions",
        _list_questions_tool,
        lambda inputs: list_worker_questions(),
    )
    tools_registered += 1

    async def reply_to_worker(request_id: str, reply: str) -> str:
        """Reply to a specific worker escalation by request_id."""
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No colony running in this session."})

        pending = getattr(session, "pending_escalations", None)
        if pending is None:
            return json.dumps({"error": "Session has no escalation inbox."})

        entry = pending.get(request_id)
        if entry is None:
            return json.dumps(
                {
                    "error": "Unknown request_id. Call list_worker_questions() to see currently pending escalations.",
                    "request_id": request_id,
                }
            )

        worker_id = entry.get("worker_id")
        if not worker_id:
            return json.dumps({"error": "Escalation entry is missing worker_id.", "request_id": request_id})

        # Format the reply so the waiting worker's conversation shows
        # it as a queen handoff rather than a raw user message.
        reply_text = f"[QUEEN_REPLY] request_id={request_id}\n{reply}"
        try:
            delivered = await runtime.inject_input(worker_id, reply_text)
        except Exception as e:
            return json.dumps({"error": f"Failed to inject reply: {e}"})

        # Drop the entry regardless of delivery — a failed delivery
        # usually means the worker already terminated, in which case
        # it cannot be unblocked and the entry should not linger.
        pending.pop(request_id, None)

        return json.dumps(
            {
                "status": "delivered" if delivered else "worker_not_active",
                "worker_id": worker_id,
                "request_id": request_id,
            }
        )

    _reply_tool = Tool(
        name="reply_to_worker",
        description=(
            "Reply to a specific worker escalation. The reply is injected "
            "into the identified worker's conversation so it can resume. "
            "Use list_worker_questions() to discover pending request_ids."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The escalation request_id from list_worker_questions.",
                },
                "reply": {
                    "type": "string",
                    "description": "Guidance or answer text to hand back to the worker.",
                },
            },
            "required": ["request_id", "reply"],
        },
    )
    registry.register("reply_to_worker", _reply_tool, lambda inputs: reply_to_worker(**inputs))
    tools_registered += 1

    # --- set_trigger -----------------------------------------------------------

    async def set_trigger(
        trigger_id: str,
        trigger_type: str | None = None,
        trigger_config: dict | None = None,
        task: str | None = None,
    ) -> str:
        """Activate a trigger so it fires periodically into the queen."""
        if trigger_id in getattr(session, "active_trigger_ids", set()):
            return json.dumps({"error": f"Trigger '{trigger_id}' is already active."})

        # Look up existing or create new
        available = getattr(session, "available_triggers", {})
        tdef = available.get(trigger_id)

        if tdef is None:
            if trigger_type and trigger_config:
                from framework.host.triggers import TriggerDefinition

                tdef = TriggerDefinition(
                    id=trigger_id,
                    trigger_type=trigger_type,
                    trigger_config=trigger_config,
                )
                available[trigger_id] = tdef
            else:
                return json.dumps(
                    {
                        "error": (
                            f"Trigger '{trigger_id}' not found. "
                            "Provide trigger_type and trigger_config to create a custom trigger."
                        )
                    }
                )

        # Apply task override if provided
        if task:
            tdef.task = task

        # Task is mandatory before activation
        if not tdef.task:
            return json.dumps(
                {
                    "error": f"Trigger '{trigger_id}' has no task configured. "
                    "Set a task describing what the worker should do when this trigger fires."
                }
            )

        # Use provided overrides if given
        t_type = trigger_type or tdef.trigger_type
        t_config = trigger_config or tdef.trigger_config
        if trigger_type:
            tdef.trigger_type = t_type
        if trigger_config:
            tdef.trigger_config = t_config

        # Validate and activate by type
        if t_type == "webhook":
            path = t_config.get("path", "").strip()
            if not path or not path.startswith("/"):
                return json.dumps(
                    {
                        "error": (
                            "Webhook trigger requires 'path' starting with '/'"
                            " in trigger_config (e.g. '/hooks/github')."
                        )
                    }
                )
            valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            methods = t_config.get("methods", ["POST"])
            invalid = [m.upper() for m in methods if m.upper() not in valid_methods]
            if invalid:
                return json.dumps({"error": f"Invalid HTTP methods: {invalid}. Valid: {sorted(valid_methods)}"})

            try:
                await _start_trigger_webhook(session, trigger_id, tdef)
            except Exception as e:
                return json.dumps({"error": f"Failed to start webhook trigger: {e}"})

            tdef.active = True
            session.active_trigger_ids.add(trigger_id)
            await _persist_active_triggers(session, session_id)
            _save_trigger_to_agent(session, trigger_id, tdef)
            bus = getattr(session, "event_bus", None)
            if bus:
                _runner = getattr(session, "runner", None)
                _graph_entry = _runner.graph.entry_node if _runner else None
                await bus.publish(
                    AgentEvent(
                        type=EventType.TRIGGER_ACTIVATED,
                        stream_id="queen",
                        data={
                            "trigger_id": trigger_id,
                            "trigger_type": t_type,
                            "trigger_config": t_config,
                            "name": tdef.description or trigger_id,
                            **({"entry_node": _graph_entry} if _graph_entry else {}),
                        },
                    )
                )
            port = int(t_config.get("port", 8090))
            return json.dumps(
                {
                    "status": "activated",
                    "trigger_id": trigger_id,
                    "trigger_type": t_type,
                    "webhook_url": f"http://127.0.0.1:{port}{path}",
                }
            )

        if t_type != "timer":
            return json.dumps({"error": f"Unsupported trigger type: {t_type}"})

        cron_expr = t_config.get("cron")
        interval = t_config.get("interval_minutes")
        if cron_expr:
            try:
                from croniter import croniter

                if not croniter.is_valid(cron_expr):
                    return json.dumps({"error": f"Invalid cron expression: {cron_expr}"})
            except ImportError:
                return json.dumps({"error": "croniter package not installed — cannot validate cron expression."})
        elif interval:
            if not isinstance(interval, (int, float)) or interval <= 0:
                return json.dumps({"error": f"interval_minutes must be > 0, got {interval}"})
        else:
            return json.dumps({"error": "Timer trigger needs 'cron' or 'interval_minutes' in trigger_config."})

        # Start timer
        try:
            await _start_trigger_timer(session, trigger_id, tdef)
        except Exception as e:
            return json.dumps({"error": f"Failed to start trigger timer: {e}"})

        tdef.active = True
        session.active_trigger_ids.add(trigger_id)

        # Persist to session state and agent definition
        await _persist_active_triggers(session, session_id)
        _save_trigger_to_agent(session, trigger_id, tdef)

        # Emit event
        bus = getattr(session, "event_bus", None)
        if bus:
            _runner = getattr(session, "runner", None)
            _graph_entry = _runner.graph.entry_node if _runner else None
            await bus.publish(
                AgentEvent(
                    type=EventType.TRIGGER_ACTIVATED,
                    stream_id="queen",
                    data={
                        "trigger_id": trigger_id,
                        "trigger_type": t_type,
                        "trigger_config": t_config,
                        "name": tdef.description or trigger_id,
                        **({"entry_node": _graph_entry} if _graph_entry else {}),
                    },
                )
            )

        return json.dumps(
            {
                "status": "activated",
                "trigger_id": trigger_id,
                "trigger_type": t_type,
                "trigger_config": t_config,
            }
        )

    _set_trigger_tool = Tool(
        name="set_trigger",
        description=(
            "Activate a trigger (timer) so it fires periodically. "
            "Use trigger_id of an available trigger, or provide trigger_type + trigger_config"
            " to create a custom one. "
            "A task must be configured before activation —"
            " either pre-set on the trigger or provided here."
        ),
        parameters={
            "type": "object",
            "properties": {
                "trigger_id": {
                    "type": "string",
                    "description": ("ID of the trigger to activate (from list_triggers) or a new custom ID"),
                },
                "trigger_type": {
                    "type": "string",
                    "description": "Type of trigger ('timer'). Only needed for custom triggers.",
                },
                "trigger_config": {
                    "type": "object",
                    "description": (
                        "Config for the trigger."
                        " Timer: {cron: '*/5 * * * *'} or {interval_minutes: 5}."
                        " Only needed for custom triggers."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task/instructions for the worker when this trigger fires"
                        " (e.g. 'Process inbox emails using saved rules')."
                        " Required if not already configured on the trigger."
                    ),
                },
            },
            "required": ["trigger_id"],
        },
    )
    registry.register("set_trigger", _set_trigger_tool, lambda inputs: set_trigger(**inputs))
    tools_registered += 1

    # --- remove_trigger --------------------------------------------------------

    async def remove_trigger(trigger_id: str) -> str:
        """Deactivate an active trigger."""
        if trigger_id not in getattr(session, "active_trigger_ids", set()):
            return json.dumps({"error": f"Trigger '{trigger_id}' is not active."})

        # Cancel timer task (if timer trigger)
        task = session.active_timer_tasks.pop(trigger_id, None)
        if task and not task.done():
            task.cancel()
        getattr(session, "trigger_next_fire", {}).pop(trigger_id, None)

        # Unsubscribe webhook handler (if webhook trigger)
        webhook_subs = getattr(session, "active_webhook_subs", {})
        if sub_id := webhook_subs.pop(trigger_id, None):
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass

        session.active_trigger_ids.discard(trigger_id)

        # Mark inactive
        available = getattr(session, "available_triggers", {})
        tdef = available.get(trigger_id)
        if tdef:
            tdef.active = False

        # Persist to session state and remove from agent definition
        await _persist_active_triggers(session, session_id)
        _remove_trigger_from_agent(session, trigger_id)

        # Emit event
        bus = getattr(session, "event_bus", None)
        if bus:
            await bus.publish(
                AgentEvent(
                    type=EventType.TRIGGER_DEACTIVATED,
                    stream_id="queen",
                    data={
                        "trigger_id": trigger_id,
                        "name": tdef.description or trigger_id if tdef else trigger_id,
                    },
                )
            )

        return json.dumps({"status": "deactivated", "trigger_id": trigger_id})

    _remove_trigger_tool = Tool(
        name="remove_trigger",
        description=("Deactivate an active trigger. The trigger stops firing but remains available for re-activation."),
        parameters={
            "type": "object",
            "properties": {
                "trigger_id": {
                    "type": "string",
                    "description": "ID of the trigger to deactivate",
                },
            },
            "required": ["trigger_id"],
        },
    )
    registry.register("remove_trigger", _remove_trigger_tool, lambda inputs: remove_trigger(**inputs))
    tools_registered += 1

    # --- list_triggers ---------------------------------------------------------

    async def list_triggers() -> str:
        """List all available triggers and their status."""
        available = getattr(session, "available_triggers", {})
        triggers = []
        for tdef in available.values():
            triggers.append(
                {
                    "id": tdef.id,
                    "trigger_type": tdef.trigger_type,
                    "trigger_config": tdef.trigger_config,
                    "description": tdef.description,
                    "task": tdef.task,
                    "active": tdef.active,
                }
            )
        return json.dumps({"triggers": triggers})

    _list_triggers_tool = Tool(
        name="list_triggers",
        description=("List all available triggers (from the loaded worker) and their active/inactive status."),
        parameters={
            "type": "object",
            "properties": {},
        },
    )
    registry.register("list_triggers", _list_triggers_tool, lambda inputs: list_triggers())
    tools_registered += 1

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
