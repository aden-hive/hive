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
    working_tools: list = field(default_factory=list)  # list[Tool]
    reviewing_tools: list = field(default_factory=list)  # list[Tool]
    independent_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_PHASE_CHANGED events

    # Agent path — set after scaffolding so the frontend can query credentials
    agent_path: str | None = None

    # Phase-specific prompts (set by session_manager after construction)
    prompt_working: str = ""
    prompt_reviewing: str = ""
    prompt_independent: str = ""

    # Default skill operational protocols — appended to every phase prompt
    protocols_prompt: str = ""
    # Community skills catalog (XML) — appended after protocols
    skills_catalog_prompt: str = ""

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

    # Cached global recall block — populated async by recall_selector after each turn.
    _cached_global_recall_block: str = ""
    # Global memory directory.
    global_memory_dir: Path | None = None

    def get_current_tools(self) -> list:
        """Return tools for the current phase."""
        if self.phase == "independent":
            return list(self.independent_tools)
        if self.phase == "working":
            return list(self.working_tools)
        if self.phase == "reviewing":
            return list(self.reviewing_tools)
        return list(self.independent_tools)

    def get_current_prompt(self) -> str:
        """Return the system prompt for the current phase."""
        if self.phase == "independent":
            base = self.prompt_independent
        elif self.phase == "working":
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
        if self.skills_catalog_prompt:
            parts.append(self.skills_catalog_prompt)
        if self.protocols_prompt:
            parts.append(self.protocols_prompt)
        if self._cached_global_recall_block:
            parts.append(self._cached_global_recall_block)
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

    async def switch_to_working(self, source: str = "tool") -> None:
        if self.phase == "working":
            return
        self.phase = "working"
        tool_names = [t.name for t in self.working_tools]
        logger.info("Queen phase -> working (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to WORKING phase. "
                "Colony workers are running. You have monitoring tools: "
                + ", ".join(tool_names)
                + "."
            )

    async def switch_to_reviewing(self, source: str = "tool") -> None:
        if self.phase == "reviewing":
            return
        self.phase = "reviewing"
        tool_names = [t.name for t in self.reviewing_tools]
        logger.info("Queen phase -> reviewing (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to REVIEWING phase. "
                "Workers have completed. Review results and decide next steps. "
                "Available tools: " + ", ".join(tool_names) + "."
            )

    async def switch_to_independent(self, source: str = "tool") -> None:
        if self.phase == "independent":
            return
        self.phase = "independent"
        tool_names = [t.name for t in self.independent_tools]
        logger.info("Queen phase -> independent (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to INDEPENDENT mode. "
                "You are the agent — execute the task directly. "
                "Available tools: " + ", ".join(tool_names) + "."
            )

    planning_tools: list = field(default_factory=list)  # list[Tool]
    building_tools: list = field(default_factory=list)  # list[Tool]
    staging_tools: list = field(default_factory=list)  # list[Tool]
    running_tools: list = field(default_factory=list)  # list[Tool]
    editing_tools: list = field(default_factory=list)  # list[Tool]
    independent_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_PHASE_CHANGED events

    # Draft graph created during planning phase (lightweight, loose-validation).
    # Stored here so it persists across turns and can be consumed by building.
    draft_graph: dict | None = None
    # Whether the user has confirmed the draft and approved moving to building.
    build_confirmed: bool = False
    # Original draft preserved for flowchart display during runtime (pre-dissolution).
    original_draft_graph: dict | None = None
    # Mapping from runtime node IDs → list of original draft flowchart node IDs.
    # Built during decision-node dissolution at confirm_and_build().
    flowchart_map: dict[str, list[str]] | None = None

    # Counter for ask_user / ask_user_multiple rounds during planning phase.
    # Incremented via event bus subscription in queen_orchestrator.
    planning_ask_rounds: int = 0

    # Agent path — set after scaffolding so the frontend can query credentials
    agent_path: str | None = None

    # Phase-specific prompts (set by session_manager after construction)
    prompt_planning: str = ""
    prompt_building: str = ""
    prompt_staging: str = ""
    prompt_running: str = ""
    prompt_editing: str = ""
    prompt_independent: str = ""

    # Default skill operational protocols — appended to every phase prompt
    protocols_prompt: str = ""
    # Community skills catalog (XML) — appended after protocols
    skills_catalog_prompt: str = ""

    # Provider for the ambient "Connected integrations" block. See
    # docstring on the simpler QueenPhaseState above.
    credentials_prompt_provider: Any = None  # Callable[[], str] | None

    # Queen identity (set once at session start by queen identity hook,
    # persisted here so it survives dynamic prompt refreshes across iterations).
    queen_id: str | None = None
    queen_profile: dict | None = None
    queen_identity_prompt: str = ""

    # Cached global recall block — populated async by recall_selector after each turn.
    _cached_global_recall_block: str = ""
    # Cached queen-scoped recall block — populated async by recall_selector after each turn.
    _cached_queen_recall_block: str = ""
    # Global memory directory.
    global_memory_dir: Path | None = None
    # Queen-scoped memory directory.
    queen_memory_dir: Path | None = None

    def get_current_tools(self) -> list:
        """Return tools for the current phase."""
        if self.phase == "independent":
            return list(self.independent_tools)
        if self.phase == "planning":
            return list(self.planning_tools)
        if self.phase == "running":
            return list(self.running_tools)
        if self.phase == "staging":
            return list(self.staging_tools)
        if self.phase == "editing":
            return list(self.editing_tools)
        return list(self.building_tools)

    def get_current_prompt(self) -> str:
        """Return the system prompt for the current phase."""
        if self.phase == "independent":
            base = self.prompt_independent
        elif self.phase == "planning":
            base = self.prompt_planning
        elif self.phase == "running":
            base = self.prompt_running
        elif self.phase == "staging":
            base = self.prompt_staging
        elif self.phase == "editing":
            base = self.prompt_editing
        else:
            base = self.prompt_building

        parts = []
        if self.queen_identity_prompt:
            parts.append(self.queen_identity_prompt)
        parts.append(base)
        credentials_block = _render_credentials_block(self.credentials_prompt_provider)
        if credentials_block:
            parts.append(credentials_block)
        if self.skills_catalog_prompt:
            parts.append(self.skills_catalog_prompt)
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
        """Switch to editing phase — worker stays loaded, queen can tweak and re-run.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "editing":
            return
        self.phase = "editing"
        tool_names = [t.name for t in self.editing_tools]
        logger.info("Queen phase → editing (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to EDITING phase. "
                "Worker is still loaded. You can tweak configuration and re-run, "
                "or escalate to building/planning if a deeper change is needed. "
                "Available tools: " + ", ".join(tool_names) + "."
            )

    async def switch_to_running(self, source: str = "tool") -> None:
        """Switch to running phase and notify the queen.

        Args:
            source: Who triggered the switch — "tool" (queen LLM),
                "frontend" (user clicked Run), or "auto" (system).
        """
        if self.phase == "running":
            return
        self.phase = "running"
        tool_names = [t.name for t in self.running_tools]
        logger.info("Queen phase → running (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        # Skip notification when source="tool" — the tool result already
        # contains the phase change info.
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] The user clicked Run in the UI. Switched to RUNNING phase. "
                "Worker is now executing. You have monitoring/lifecycle tools: "
                + ", ".join(tool_names)
                + "."
            )

    async def switch_to_staging(self, source: str = "tool") -> None:
        """Switch to staging phase and notify the queen.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "staging":
            return
        self.phase = "staging"
        tool_names = [t.name for t in self.staging_tools]
        logger.info("Queen phase → staging (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        # Skip notification when source="tool" — the tool result already
        # contains the phase change info.
        if self.inject_notification and source != "tool":
            if source == "frontend":
                msg = (
                    "[PHASE CHANGE] The user stopped the worker from the UI. "
                    "Switched to STAGING phase. Agent is still loaded. "
                    "Available tools: " + ", ".join(tool_names) + "."
                )
            else:
                msg = (
                    "[PHASE CHANGE] Worker execution completed. Switched to STAGING phase. "
                    "Agent is still loaded. Call run_agent_with_input(task) to run again. "
                    "Available tools: " + ", ".join(tool_names) + "."
                )
            await self.inject_notification(msg)

    async def switch_to_building(self, source: str = "tool") -> None:
        """Switch to building phase and notify the queen.

        Blocked from RUNNING and EDITING.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "building":
            return
        if self.phase in ("running", "editing"):
            logger.warning(
                "Queen phase: BLOCKED %s → building (source=%s)",
                self.phase,
                source,
            )
            return
        self.phase = "building"
        tool_names = [t.name for t in self.building_tools]
        logger.info("Queen phase → building (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to BUILDING phase. "
                "Lifecycle tools removed. Full coding tools restored. "
                "Call load_built_agent(path) when ready to stage."
            )

    async def switch_to_planning(self, source: str = "tool") -> None:
        """Switch to planning phase and notify the queen.

        Blocked from RUNNING and EDITING.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "planning":
            return
        if self.phase in ("running", "editing"):
            logger.warning(
                "Queen phase: BLOCKED %s → planning (source=%s)",
                self.phase,
                source,
            )
            return
        self.phase = "planning"
        tool_names = [t.name for t in self.planning_tools]
        logger.info("Queen phase → planning (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        # Skip notification when source="tool" — the tool result already
        # contains the phase change info; injecting a duplicate notification
        # causes the queen to respond twice.
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to PLANNING phase. "
                "Coding tools removed. Discuss goals and design with the user. "
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
            tid: available[tid].task
            for tid in active_ids
            if tid in available and available[tid].task
        }
        await store.write_state(session_id, state)
    except Exception:
        logger.warning(
            "Failed to persist active triggers for session %s", session_id, exc_info=True
        )


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


def _dissolve_planning_nodes(
    draft: dict,
) -> tuple[dict, dict[str, list[str]]]:
    """Convert planning-only nodes into runtime-compatible structures.

    Two kinds of planning-only nodes are dissolved:

    **Decision nodes** (flowchart diamonds):
    1. Merging the decision clause into the predecessor node's success_criteria.
    2. Rewiring the decision's yes/no outgoing edges as on_success/on_failure
       edges from the predecessor.
    3. Removing the decision node from the graph.

    If a decision node has no predecessor (i.e. it's the first node), it is
    converted to a regular process node instead of being dissolved.

    **Sub-agent nodes** (flowchart subroutines):
    1. Adding the sub-agent's ID to the predecessor's sub_agents list.
    2. Removing the sub-agent node and its edges.

    Returns (converted_draft, flowchart_map) where flowchart_map maps each
    surviving runtime node ID to the list of original draft node IDs it absorbed.
    """
    import copy as _copy

    nodes: list[dict] = _copy.deepcopy(draft.get("nodes", []))
    edges: list[dict] = _copy.deepcopy(draft.get("edges", []))

    # Index helpers
    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    def _incoming(nid: str) -> list[dict]:
        return [e for e in edges if e["target"] == nid]

    def _outgoing(nid: str) -> list[dict]:
        return [e for e in edges if e["source"] == nid]

    # Identify decision nodes
    decision_ids = [n["id"] for n in nodes if n.get("flowchart_type") == "decision"]

    # Track which draft nodes each runtime node absorbed
    absorbed: dict[str, list[str]] = {}  # runtime_id -> [draft_ids...]

    # Process decisions in node-list order (topological for linear graphs)
    for d_id in decision_ids:
        d_node = node_by_id.get(d_id)
        if d_node is None:
            continue  # already removed by a prior dissolution

        in_edges = _incoming(d_id)
        out_edges = _outgoing(d_id)

        # Classify outgoing edges into yes/no branches
        yes_edge: dict | None = None
        no_edge: dict | None = None

        for oe in out_edges:
            lbl = (oe.get("label") or "").lower().strip()
            cond = (oe.get("condition") or "").lower().strip()

            if lbl in ("yes", "true", "pass") or cond == "on_success":
                yes_edge = oe
            elif lbl in ("no", "false", "fail") or cond == "on_failure":
                no_edge = oe

        # Fallback: if exactly 2 outgoing and couldn't classify, assign by order
        if len(out_edges) == 2 and (yes_edge is None or no_edge is None):
            if yes_edge is None and no_edge is None:
                yes_edge, no_edge = out_edges[0], out_edges[1]
            elif yes_edge is None:
                yes_edge = [e for e in out_edges if e is not no_edge][0]
            else:
                no_edge = [e for e in out_edges if e is not yes_edge][0]

        # Decision clause: prefer decision_clause, fall back to description/name
        clause = (
            d_node.get("decision_clause") or d_node.get("description") or d_node.get("name") or d_id
        ).strip()

        predecessors = [node_by_id[e["source"]] for e in in_edges if e["source"] in node_by_id]

        if not predecessors:
            # Decision at start: convert to regular process node
            d_node["flowchart_type"] = "process"
            fc_meta = FLOWCHART_TYPES["process"]
            d_node["flowchart_shape"] = fc_meta["shape"]
            d_node["flowchart_color"] = fc_meta["color"]
            if not d_node.get("success_criteria"):
                d_node["success_criteria"] = clause
            # Rewire outgoing edges to on_success/on_failure
            if yes_edge:
                yes_edge["condition"] = "on_success"
            if no_edge:
                no_edge["condition"] = "on_failure"
            absorbed[d_id] = absorbed.get(d_id, [d_id])
            continue

        # Dissolve: merge into each predecessor
        for pred in predecessors:
            pid = pred["id"]

            # Merge decision clause into predecessor's success_criteria
            existing = (pred.get("success_criteria") or "").strip()
            if existing:
                pred["success_criteria"] = f"{existing}; then evaluate: {clause}"
            else:
                pred["success_criteria"] = clause

            # Remove the edge from predecessor -> decision
            edges[:] = [e for e in edges if not (e["source"] == pid and e["target"] == d_id)]

            # Wire predecessor -> yes/no targets
            edge_counter = len(edges)
            if yes_edge:
                edges.append(
                    {
                        "id": f"edge-dissolved-{edge_counter}",
                        "source": pid,
                        "target": yes_edge["target"],
                        "condition": "on_success",
                        "description": yes_edge.get("description", ""),
                        "label": yes_edge.get("label", "Yes"),
                    }
                )
                edge_counter += 1
            if no_edge:
                edges.append(
                    {
                        "id": f"edge-dissolved-{edge_counter}",
                        "source": pid,
                        "target": no_edge["target"],
                        "condition": "on_failure",
                        "description": no_edge.get("description", ""),
                        "label": no_edge.get("label", "No"),
                    }
                )

            # Record absorption
            prev_absorbed = absorbed.get(pid, [pid])
            if d_id not in prev_absorbed:
                prev_absorbed.append(d_id)
            absorbed[pid] = prev_absorbed

        # Remove decision node and all its edges
        edges[:] = [e for e in edges if e["source"] != d_id and e["target"] != d_id]
        nodes[:] = [n for n in nodes if n["id"] != d_id]
        del node_by_id[d_id]

    # Build complete flowchart_map (identity for non-absorbed nodes)
    flowchart_map: dict[str, list[str]] = {}
    for n in nodes:
        nid = n["id"]
        flowchart_map[nid] = absorbed.get(nid, [nid])

    # Rebuild terminal_nodes (decision targets may have changed)
    sources = {e["source"] for e in edges}
    all_ids = {n["id"] for n in nodes}
    terminal_ids = all_ids - sources
    if not terminal_ids and nodes:
        terminal_ids = {nodes[-1]["id"]}

    converted = dict(draft)
    converted["nodes"] = nodes
    converted["edges"] = edges
    converted["terminal_nodes"] = sorted(terminal_ids)
    converted["entry_node"] = nodes[0]["id"] if nodes else ""

    return converted, flowchart_map


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
    # top). The shared preflight timeout below is still used by
    # ``run_agent_with_input``.
    _START_PREFLIGHT_TIMEOUT = 15  # seconds

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
                stopped_unified = sum(
                    1 for w in colony.list_workers() if w.status.value in ("pending", "running")
                )
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
            "Cancel all active colony workers and pause timers. "
            "Workers stop gracefully. No parameters needed."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("stop_worker", _stop_tool, lambda inputs: stop_worker())
    tools_registered += 1

    # --- run_parallel_workers --------------------------------------------------
    #
    # Phase 4 fan-out tool. Reads the unified ColonyRuntime from
    # ``session.colony`` (built by SessionManager._start_unified_colony_runtime),
    # spawns one Worker per task spec via spawn_batch, then blocks on
    # wait_for_worker_reports until every worker has reported (or the
    # timeout fires and stragglers are force-stopped). Returns a JSON
    # array of structured reports {worker_id, status, summary, data,
    # error, duration_seconds, tokens_used} that the queen reads on its
    # next turn and aggregates into a user-facing summary.
    #
    # Worker SUBAGENT_REPORT events flow through session.event_bus, so
    # the existing SSE pipeline surfaces them automatically. Workers'
    # individual LLM deltas / tool calls also publish to the same bus
    # under stream_id="worker:{worker_id}"; SSE filtering for those is
    # Phase 5 — for now they reach the queen DM channel.

    _RUN_PARALLEL_DEFAULT_TIMEOUT = 600.0  # 10 minutes per batch

    def _get_unified_colony():
        """Read the unified ColonyRuntime (Phase 2 wiring) from session."""
        return getattr(session, "colony", None)

    async def run_parallel_workers(
        *,
        tasks: list[dict],
        timeout: float | None = None,
    ) -> str:
        """Spawn N parallel workers and wait for all reports.

        Each task is a dict ``{"task": str, "data": dict | None}``.
        Returns a JSON array of structured reports in input order.
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
            return json.dumps(
                {"error": "tasks must be a non-empty list of {task, data?} dicts"}
            )

        # Hard ceiling on a single fan-out call. A runaway queen requesting
        # thousands of parallel workers would starve memory and drown the
        # event loop; reject early with a clear error instead.
        _RUN_PARALLEL_HARD_CAP = 64
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
                return json.dumps(
                    {"error": f"tasks[{i}] is not a dict: {type(spec).__name__}"}
                )
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
            worker_ids = await colony.spawn_batch(normalised)
        except Exception as e:
            return json.dumps({"error": f"spawn_batch failed: {e}"})

        try:
            reports = await colony.wait_for_worker_reports(
                worker_ids,
                timeout=timeout if timeout is not None else _RUN_PARALLEL_DEFAULT_TIMEOUT,
            )
        except Exception as e:
            return json.dumps(
                {
                    "error": f"wait_for_worker_reports failed: {e}",
                    "worker_ids": worker_ids,
                }
            )

        return json.dumps(
            {
                "worker_count": len(reports),
                "reports": reports,
            }
        )

    _run_parallel_tool = Tool(
        name="run_parallel_workers",
        description=(
            "Fan out a batch of tasks to parallel workers and wait for all "
            "reports. Use this when you can split the work into independent "
            "subtasks that can run concurrently (e.g. fetching N batches "
            "from an API, processing M files, comparing K candidates).\n\n"
            "CRITICAL: each worker is a FRESH process with NO memory of "
            "your conversation. Every task string must be FULLY "
            "self-contained — include the API endpoint, the exact "
            "parameters, the expected output format, and any "
            "constraints. Workers cannot ask the user follow-up "
            "questions and cannot see your chat history. Write each "
            "task as if handing it to a stranger.\n\n"
            "Each worker runs in isolation with its own AgentLoop and "
            "reports back via the report_to_parent tool. The call "
            "blocks until every worker has reported or the timeout "
            "fires. Returns a JSON object with a 'reports' array; each "
            "report has worker_id, status "
            "(success|partial|failed|timeout|stopped), summary, data, "
            "error, duration_seconds, and tokens_used. Read the "
            "summaries on your next turn and synthesize a user-facing "
            "result. Default timeout is 600 seconds (10 minutes)."
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
                        "Per-batch timeout in seconds. Workers still "
                        "running when the timeout fires are force-stopped "
                        "and reported as status='timeout'. Default 600."
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
    # Forks the current queen session into a colony. Requires the queen
    # to have ALREADY AUTHORED a skill folder capturing what she learned
    # during this session (using her write_file / edit_file tools), and
    # pass the folder path to this tool. The tool validates the skill
    # folder (SKILL.md exists, frontmatter has the required ``name`` +
    # ``description`` fields, directory name matches frontmatter name),
    # then forks. If the skill lives outside ``~/.hive/skills/`` the
    # tool copies it in so the new colony's worker will discover it on
    # its first skill scan.
    #
    # This is the codified version of the user's instruction:
    #
    #   "When the queen agent needs to create a colony, it needs to
    #    write down whatever it just learned from the current session
    #    as an agent skill and put it in the ~/.hive/skills folder."
    #
    # Two-step flow for the queen LLM:
    #
    #   1. Author the skill with write_file (or a sequence of writes
    #      for scripts/references/assets subdirs) — she already knows
    #      the format via the writing-hive-skills default skill.
    #   2. Call create_colony(colony_name, task, skill_path) pointing
    #      at the folder she just wrote.

    import re as _re
    import shutil as _shutil

    _COLONY_NAME_RE = _re.compile(r"^[a-z0-9_]+$")
    _SKILL_NAME_RE = _re.compile(r"^[a-z0-9-]+$")

    def _validate_and_install_skill(skill_path: str) -> tuple[Path | None, str | None]:
        """Validate an authored skill folder and ensure it lives under ~/.hive/skills/.

        Returns ``(installed_path, error)``. On success ``error`` is
        ``None`` and ``installed_path`` is the final location under
        ``~/.hive/skills/{name}/``. On failure ``installed_path`` is
        ``None`` and ``error`` is a human-readable reason suitable for
        returning to the queen as a JSON error payload.
        """
        if not skill_path or not isinstance(skill_path, str):
            return None, "skill_path must be a non-empty string"

        src = Path(skill_path).expanduser().resolve()
        if not src.exists():
            return None, f"skill_path does not exist: {src}"
        if not src.is_dir():
            return None, f"skill_path must be a directory, got file: {src}"

        skill_md = src / "SKILL.md"
        if not skill_md.is_file():
            return None, f"skill_path has no SKILL.md at {skill_md}"

        # Parse the frontmatter to pull out the name and verify
        # description exists. We don't need a full YAML parser — the
        # writing-hive-skills protocol is rigid enough that a line-by-line
        # scan of the first frontmatter block suffices for validation.
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError as e:
            return None, f"failed to read SKILL.md: {e}"

        if not content.startswith("---"):
            return None, "SKILL.md missing opening '---' frontmatter marker"
        after_open = content.split("---", 2)
        if len(after_open) < 3:
            return None, "SKILL.md missing closing '---' frontmatter marker"
        frontmatter_text = after_open[1]

        fm_name: str | None = None
        fm_description: str | None = None
        for raw_line in frontmatter_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("name:"):
                fm_name = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("description:"):
                fm_description = line.split(":", 1)[1].strip().strip('"').strip("'")

        if not fm_name:
            return None, "SKILL.md frontmatter missing 'name' field"
        if not fm_description:
            return None, "SKILL.md frontmatter missing 'description' field"
        if not (1 <= len(fm_description) <= 1024):
            return None, "SKILL.md 'description' must be 1–1024 chars"
        if not _SKILL_NAME_RE.match(fm_name):
            return None, (
                f"SKILL.md 'name' field '{fm_name}' must match [a-z0-9-] "
                "pattern"
            )
        if fm_name.startswith("-") or fm_name.endswith("-") or "--" in fm_name:
            return None, (
                f"SKILL.md 'name' '{fm_name}' has leading/trailing/"
                "consecutive hyphens"
            )
        if len(fm_name) > 64:
            return None, f"SKILL.md 'name' '{fm_name}' exceeds 64 chars"

        # The directory basename should match the frontmatter name —
        # this is the writing-hive-skills convention. We ENFORCE it
        # because the skill loader uses dir names as identity.
        if src.name != fm_name:
            return None, (
                f"skill directory name '{src.name}' does not match "
                f"SKILL.md frontmatter name '{fm_name}'. Rename the "
                "folder or fix the frontmatter."
            )

        # Install into ~/.hive/skills/{name}/ if not already there.
        target_root = Path.home() / ".hive" / "skills"
        target = target_root / fm_name
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return None, f"failed to create skills root: {e}"

        try:
            if src.resolve() == target.resolve():
                # Already in the right place — nothing to do.
                return target, None
        except OSError:
            pass

        try:
            if target.exists():
                # Overwrite existing — the queen is explicitly creating
                # a new colony for this version, so her authored skill
                # wins over any prior version. copytree with
                # dirs_exist_ok handles subdirs (scripts/, references/,
                # assets/) but does NOT delete files removed in the
                # new version. For a clean overwrite we rmtree first.
                _shutil.rmtree(target)
            _shutil.copytree(src, target)
        except OSError as e:
            return None, f"failed to install skill into {target}: {e}"

        # Cleanup the source directory after a successful install so
        # the authored skill doesn't linger as debris in the agent
        # workspace (or — pre-sandbox-split — in the hive git
        # checkout). Only removes paths that are OUTSIDE
        # ``~/.hive/skills/`` so we never nuke the canonical install
        # target or user-owned skill dirs.
        try:
            src_resolved = src.resolve()
            skills_root_resolved = target_root.resolve()
            try:
                src_resolved.relative_to(skills_root_resolved)
                _under_skills_root = True
            except ValueError:
                _under_skills_root = False
            if not _under_skills_root:
                _shutil.rmtree(src_resolved)
                logger.info(
                    "create_colony: cleaned up authored skill source at %s "
                    "(installed to %s)",
                    src_resolved,
                    target,
                )
        except OSError as e:
            logger.warning(
                "create_colony: failed to clean up skill source at %s (non-fatal): %s",
                src,
                e,
            )

        return target, None

    async def create_colony(
        *,
        colony_name: str,
        task: str,
        skill_path: str,
        tasks: list[dict] | None = None,
    ) -> str:
        """Create a colony after installing a pre-authored skill folder.

        File-system only: copies the queen session into a new colony
        directory and writes ``worker.json`` with the task baked in.
        NOTHING RUNS after fork. The user navigates to the colony when
        they're ready to start the worker — at that point the worker
        reads the task from ``worker.json`` and the skill from
        ``~/.hive/skills/`` and starts informed.

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
                {
                    "error": (
                        "colony_name must be lowercase alphanumeric "
                        "with underscores (e.g. 'honeycomb_research')."
                    )
                }
            )

        installed_skill, skill_err = _validate_and_install_skill(skill_path)
        if skill_err is not None:
            return json.dumps(
                {
                    "error": skill_err,
                    "hint": (
                        "Author the skill folder first using write_file "
                        "(and edit_file for follow-ups). The folder must "
                        "contain a SKILL.md with YAML frontmatter "
                        "{name, description} — see your "
                        "writing-hive-skills default skill for the "
                        "format. Then call create_colony again with "
                        "skill_path pointing at that folder."
                    ),
                }
            )

        logger.info(
            "create_colony: installed skill from %s → %s",
            skill_path,
            installed_skill,
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
            "Before forking, you author a Hive Skill folder capturing "
            "the operational procedure the colony worker needs to run "
            "unattended, and pass its path to this tool. The tool "
            "validates the skill folder (SKILL.md present, frontmatter "
            "name+description valid, directory name matches frontmatter "
            "name), installs it under ~/.hive/skills/{name}/ if it's "
            "not already there, and then forks the session.\n\n"
            "NOTHING RUNS AFTER FORK. This tool is file-system only: "
            "it copies the queen session into a new colony directory "
            "and writes worker.json with the task baked in. No worker "
            "is started. The user navigates to the new colony when "
            "they're ready to begin actual work (or wires up a "
            "trigger) — at that point the worker reads the task from "
            "worker.json and the skill you wrote here, and starts "
            "informed instead of clueless.\n\n"
            "TWO-STEP FLOW:\n\n"
            "  1. Use write_file (plus edit_file / list_directory as "
            "     needed) to create a skill folder. The folder must "
            "     contain a SKILL.md with YAML frontmatter {name, "
            "     description} and a markdown body. Optional subdirs: "
            "     scripts/, references/, assets/. See your "
            "     writing-hive-skills default skill for the spec. We "
            "     recommend authoring it directly at "
            "     ~/.hive/skills/{skill-name}/SKILL.md so no copy is "
            "     needed.\n"
            "  2. Call create_colony(colony_name, task, skill_path) "
            "     pointing at the folder you just wrote.\n\n"
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
            "target: 300–2000 chars of body."
        ),
        parameters={
            "type": "object",
            "properties": {
                "colony_name": {
                    "type": "string",
                    "description": (
                        "Lowercase alphanumeric+underscore name for "
                        "the new colony (e.g. 'honeycomb_research')."
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
                "skill_path": {
                    "type": "string",
                    "description": (
                        "Path to a pre-authored skill folder containing "
                        "SKILL.md. May be absolute or ~-expanded. The "
                        "directory basename MUST match the SKILL.md "
                        "frontmatter 'name' field. If the path is "
                        "outside ~/.hive/skills/ the folder is copied "
                        "in. Example: '~/.hive/skills/honeycomb-api-"
                        "protocol'."
                    ),
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
            "required": ["colony_name", "task", "skill_path"],
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

    # --- stop_worker_and_review --------------------------------------------------

    async def stop_worker_and_review() -> str:
        """Stop the loaded graph and switch to building phase for editing the agent."""
        stop_result = await stop_worker()

        # Switch to building phase
        if phase_state is not None:
            await phase_state.switch_to_building()
            _update_meta_json(session_manager, manager_session_id, {"phase": "building"})

        result = json.loads(stop_result)
        result["phase"] = "building"
        result["message"] = (
            "Graph stopped. You are now in building phase. "
            "Use your coding tools to modify the agent, then call "
            "load_built_agent(path) to stage it again."
        )
        # Nudge the queen to start coding instead of blocking for user input.
        if phase_state is not None and phase_state.inject_notification:
            await phase_state.inject_notification(
                "[PHASE CHANGE] Switched to BUILDING phase. Start implementing the changes now."
            )
        return json.dumps(result)

    _stop_edit_tool = Tool(
        name="stop_worker_and_review",
        description=(
            "Stop the running graph and switch to building phase. "
            "Use this when you need to modify the agent's code, nodes, or configuration. "
            "After editing, call load_built_agent(path) to reload and run."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "stop_worker_and_review", _stop_edit_tool, lambda inputs: stop_worker_and_review()
    )
    tools_registered += 1

    # --- stop_worker_and_plan (Running/Staging → Planning) ---------------------

    async def stop_worker_and_plan() -> str:
        """Stop the loaded graph and switch to planning phase for diagnosis."""
        stop_result = await stop_worker()

        # Switch to planning phase
        if phase_state is not None:
            await phase_state.switch_to_planning(source="tool")

        result = json.loads(stop_result)
        result["phase"] = "planning"
        result["message"] = (
            "Graph stopped. You are now in planning phase. "
            "Diagnose the issue using read-only tools (checkpoints, logs, sessions), "
            "discuss a fix plan with the user, then call "
            "initialize_and_build_agent() to implement the fix."
        )
        return json.dumps(result)

    _stop_plan_tool = Tool(
        name="stop_worker_and_plan",
        description=(
            "Stop the graph and switch to planning phase for diagnosis. "
            "Use this when you need to investigate an issue before fixing it. "
            "After diagnosis, call initialize_and_build_agent() to switch to building."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "stop_worker_and_plan", _stop_plan_tool, lambda inputs: stop_worker_and_plan()
    )
    tools_registered += 1

    # --- replan_agent (Building → Planning) -----------------------------------

    async def replan_agent() -> str:
        """Switch from building back to planning phase.
        Only use when the user explicitly asks to re-plan."""
        if phase_state is not None:
            if phase_state.phase != "building":
                return json.dumps(
                    {"error": f"Cannot replan: currently in {phase_state.phase} phase."}
                )

            # Carry forward the current draft: restore original (pre-dissolution)
            # draft so the queen can edit it in planning, rather than starting
            # from scratch.
            if phase_state.original_draft_graph is not None:
                phase_state.draft_graph = phase_state.original_draft_graph
                phase_state.original_draft_graph = None
                phase_state.flowchart_map = None
            phase_state.build_confirmed = False

            await phase_state.switch_to_planning(source="tool")

            # Re-emit draft so frontend shows the flowchart in planning mode
            bus = phase_state.event_bus
            if bus is not None and phase_state.draft_graph is not None:
                try:
                    await bus.publish(
                        AgentEvent(
                            type=EventType.CUSTOM,
                            stream_id="queen",
                            data={"event": "draft_updated", **phase_state.draft_graph},
                        )
                    )
                except Exception:
                    logger.warning("Failed to re-emit draft during replan", exc_info=True)

        has_draft = phase_state is not None and phase_state.draft_graph is not None
        return json.dumps(
            {
                "status": "replanning",
                "phase": "planning",
                "has_previous_draft": has_draft,
                "message": (
                    "Switched to PLANNING phase. Coding tools removed. "
                    + (
                        "The previous draft flowchart has been restored (with "
                        "decision and sub-agent nodes intact). Call save_agent_draft() "
                        "to update the design, then confirm_and_build() when ready."
                        if has_draft
                        else "Discuss the new design with the user."
                    )
                ),
            }
        )

    _replan_tool = Tool(
        name="replan_agent",
        description=(
            "Switch from building back to planning phase. "
            "Use when the user wants to change integrations, swap tools, "
            "rethink the flow, or discuss design changes before building them."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("replan_agent", _replan_tool, lambda inputs: replan_agent())
    tools_registered += 1

    # --- save_agent_draft (Planning phase — declarative preview) ----------------
    # so the frontend can render the graph during planning (before any code).

    def _dissolve_planning_nodes(
        draft: dict,
    ) -> tuple[dict, dict[str, list[str]]]:
        """Convert planning-only nodes into runtime-compatible structures.

        Two kinds of planning-only nodes are dissolved:

        **Decision nodes** (flowchart diamonds):
        1. Merging the decision clause into the predecessor node's success_criteria.
        2. Rewiring the decision's yes/no outgoing edges as on_success/on_failure
           edges from the predecessor.
        3. Removing the decision node from the graph.

        **Sub-agent / browser nodes** (node_type == "gcu" or flowchart_type == "browser"):
        1. Adding the sub-agent node's ID to the predecessor's sub_agents list.
        2. Removing the sub-agent node and its connecting edge.
        3. Sub-agent nodes must not have outgoing edges (they are leaf delegates).

        Returns (converted_draft, flowchart_map) where flowchart_map maps
        runtime node IDs → list of original draft node IDs they absorbed.
        """
        import copy as _copy

        nodes: list[dict] = _copy.deepcopy(draft.get("nodes", []))
        edges: list[dict] = _copy.deepcopy(draft.get("edges", []))

        # Index helpers
        node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

        def _incoming(nid: str) -> list[dict]:
            return [e for e in edges if e["target"] == nid]

        def _outgoing(nid: str) -> list[dict]:
            return [e for e in edges if e["source"] == nid]

        # Identify decision nodes
        decision_ids = [n["id"] for n in nodes if n.get("flowchart_type") == "decision"]

        # Track which draft nodes each runtime node absorbed
        absorbed: dict[str, list[str]] = {}  # runtime_id → [draft_ids...]

        # Process decisions in node-list order (topological for linear graphs)
        for d_id in decision_ids:
            d_node = node_by_id.get(d_id)
            if d_node is None:
                continue  # already removed by a prior dissolution

            in_edges = _incoming(d_id)
            out_edges = _outgoing(d_id)

            # Classify outgoing edges into yes/no branches
            yes_edge: dict | None = None
            no_edge: dict | None = None

            for oe in out_edges:
                lbl = (oe.get("label") or "").lower().strip()
                cond = (oe.get("condition") or "").lower().strip()

                if lbl in ("yes", "true", "pass") or cond == "on_success":
                    yes_edge = oe
                elif lbl in ("no", "false", "fail") or cond == "on_failure":
                    no_edge = oe

            # Fallback: if exactly 2 outgoing and couldn't classify, assign by order
            if len(out_edges) == 2 and (yes_edge is None or no_edge is None):
                if yes_edge is None and no_edge is None:
                    yes_edge, no_edge = out_edges[0], out_edges[1]
                elif yes_edge is None:
                    yes_edge = [e for e in out_edges if e is not no_edge][0]
                else:
                    no_edge = [e for e in out_edges if e is not yes_edge][0]

            # Decision clause: prefer decision_clause, fall back to description/name
            clause = (
                d_node.get("decision_clause")
                or d_node.get("description")
                or d_node.get("name")
                or d_id
            ).strip()

            predecessors = [node_by_id[e["source"]] for e in in_edges if e["source"] in node_by_id]

            if not predecessors:
                # Decision at start: convert to regular process node
                d_node["flowchart_type"] = "process"
                fc_meta = FLOWCHART_TYPES["process"]
                d_node["flowchart_shape"] = fc_meta["shape"]
                d_node["flowchart_color"] = fc_meta["color"]
                if not d_node.get("success_criteria"):
                    d_node["success_criteria"] = clause
                # Rewire outgoing edges to on_success/on_failure
                if yes_edge:
                    yes_edge["condition"] = "on_success"
                if no_edge:
                    no_edge["condition"] = "on_failure"
                absorbed[d_id] = absorbed.get(d_id, [d_id])
                continue

            # Dissolve: merge into each predecessor
            for pred in predecessors:
                pid = pred["id"]

                # Merge decision clause into predecessor's success_criteria
                existing = (pred.get("success_criteria") or "").strip()
                if existing:
                    pred["success_criteria"] = f"{existing}; then evaluate: {clause}"
                else:
                    pred["success_criteria"] = clause

                # Remove the edge from predecessor → decision
                edges[:] = [e for e in edges if not (e["source"] == pid and e["target"] == d_id)]

                # Wire predecessor → yes/no targets
                edge_counter = len(edges)
                if yes_edge:
                    edges.append(
                        {
                            "id": f"edge-dissolved-{edge_counter}",
                            "source": pid,
                            "target": yes_edge["target"],
                            "condition": "on_success",
                            "description": yes_edge.get("description", ""),
                            "label": yes_edge.get("label", "Yes"),
                        }
                    )
                    edge_counter += 1
                if no_edge:
                    edges.append(
                        {
                            "id": f"edge-dissolved-{edge_counter}",
                            "source": pid,
                            "target": no_edge["target"],
                            "condition": "on_failure",
                            "description": no_edge.get("description", ""),
                            "label": no_edge.get("label", "No"),
                        }
                    )

                # Record absorption
                prev_absorbed = absorbed.get(pid, [pid])
                if d_id not in prev_absorbed:
                    prev_absorbed.append(d_id)
                absorbed[pid] = prev_absorbed

            # Remove decision node and all its edges
            edges[:] = [e for e in edges if e["source"] != d_id and e["target"] != d_id]
            nodes[:] = [n for n in nodes if n["id"] != d_id]
            del node_by_id[d_id]

        # Build complete flowchart_map (identity for non-absorbed nodes)
        flowchart_map: dict[str, list[str]] = {}
        for n in nodes:
            nid = n["id"]
            flowchart_map[nid] = absorbed.get(nid, [nid])

        # Rebuild terminal_nodes (decision targets may have changed).
        sources = {e["source"] for e in edges}
        all_ids = {n["id"] for n in nodes}
        terminal_ids = all_ids - sources
        if not terminal_ids and nodes:
            terminal_ids = {nodes[-1]["id"]}

        converted = dict(draft)
        converted["nodes"] = nodes
        converted["edges"] = edges
        converted["terminal_nodes"] = sorted(terminal_ids)
        converted["entry_node"] = nodes[0]["id"] if nodes else ""

        return converted, flowchart_map

    async def save_agent_draft(
        *,
        agent_name: str,
        goal: str,
        nodes: list[dict],
        edges: list[dict] | None = None,
        description: str = "",
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        terminal_nodes: list[str] | None = None,
    ) -> str:
        """Save a declarative draft of the agent graph during planning.

        This creates a lightweight, visual-only graph for the user to review.
        No executable code is generated. Nodes need only an id, name, and
        description. Tools, input/output keys, and system prompts are optional
        metadata hints — they will be fully specified during the building phase.

        Each node is classified into a classical flowchart component type
        (start, terminal, process, decision, io, subprocess, browser, manual)
        with a unique color. The queen can override auto-detection by setting
        flowchart_type explicitly on a node.
        """
        # ── Gate: require at least 2 rounds of user questions ─────────
        if (
            phase_state is not None
            and phase_state.phase == "planning"
            and phase_state.planning_ask_rounds < 2
        ):
            return json.dumps(
                {
                    "error": (
                        "You haven't asked enough questions yet. You have only "
                        f"asked {phase_state.planning_ask_rounds} round(s) of "
                        "questions — at least 2 are required before saving a "
                        "draft. Think deeper and ask more practical questions "
                        "to fully understand the user's requirements before "
                        "designing the agent graph."
                    )
                }
            )

        # ── Gate: require at least 5 nodes for a meaningful graph ─────
        if len(nodes) < 5:
            return json.dumps(
                {
                    "error": (
                        f"Draft only has {len(nodes)} node(s) — at least 5 are "
                        "required for a meaningful agent graph. Think deeper and "
                        "ask more practical questions to fully understand the "
                        "user's requirements, then design a more thorough graph."
                    )
                }
            )

        # Loose validation: each node needs at minimum an id
        validated_nodes = []
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                return json.dumps({"error": f"Node {i} must be a dict, got {type(n).__name__}"})
            node_id = n.get("id", "").strip()
            if not node_id:
                return json.dumps({"error": f"Node {i} is missing 'id'"})
            validated_nodes.append(
                {
                    "id": node_id,
                    "name": n.get("name", node_id.replace("-", " ").replace("_", " ").title()),
                    "description": n.get("description", ""),
                    "node_type": n.get("node_type", "event_loop"),
                    # Optional business-logic hints (not validated yet)
                    "tools": n.get("tools", []),
                    "input_keys": n.get("input_keys", []),
                    "output_keys": n.get("output_keys", []),
                    "success_criteria": n.get("success_criteria", ""),
                    # Decision nodes: the yes/no question to evaluate
                    "decision_clause": n.get("decision_clause", ""),
                    # Explicit flowchart override (preserved for classification)
                    "flowchart_type": n.get("flowchart_type", ""),
                }
            )

        # Check for duplicate node IDs
        seen_ids: set[str] = set()
        for n in validated_nodes:
            if n["id"] in seen_ids:
                return json.dumps({"error": f"Duplicate node id '{n['id']}'"})
            seen_ids.add(n["id"])

        validated_edges = []
        if edges:
            node_ids = {n["id"] for n in validated_nodes}
            for i, e in enumerate(edges):
                if not isinstance(e, dict):
                    return json.dumps({"error": f"Edge {i} must be a dict"})
                src = e.get("source", "")
                tgt = e.get("target", "")
                if src and src not in node_ids:
                    return json.dumps({"error": f"Edge {i} source '{src}' references unknown node"})
                if tgt and tgt not in node_ids:
                    return json.dumps({"error": f"Edge {i} target '{tgt}' references unknown node"})
                validated_edges.append(
                    {
                        "id": e.get("id", f"edge-{i}"),
                        "source": src,
                        "target": tgt,
                        "condition": e.get("condition", "on_success"),
                        "description": e.get("description", ""),
                        "label": e.get("label", ""),
                    }
                )

        topology_corrections: list[str] = []

        # ── Validate graph connectivity ─────────────────────────────
        # Every node must be reachable from the entry node. Disconnected
        # subgraphs indicate a broken design — remove unreachable nodes
        # and report them so the queen can fix the draft.
        if validated_nodes:
            entry_id = validated_nodes[0]["id"]
            # Build undirected adjacency from edges
            _adj: dict[str, set[str]] = {n["id"]: set() for n in validated_nodes}
            for e in validated_edges:
                s, t = e["source"], e["target"]
                if s in _adj and t in _adj:
                    _adj[s].add(t)
                    _adj[t].add(s)
            # BFS from entry
            visited: set[str] = set()
            queue = [entry_id]
            while queue:
                cur = queue.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                for nb in _adj.get(cur, ()):
                    if nb not in visited:
                        queue.append(nb)
            unreachable = {n["id"] for n in validated_nodes} - visited
            if unreachable:
                for uid in sorted(unreachable):
                    logger.warning(
                        "Node '%s' is unreachable from entry node '%s' "
                        "— removing it from the draft.",
                        uid,
                        entry_id,
                    )
                    topology_corrections.append(
                        f"Node '{uid}' is disconnected from the graph "
                        f"(unreachable from entry node '{entry_id}') — "
                        f"removed. Connect it to the flow or assign it "
                        f"as a sub-agent of an existing node."
                    )
                validated_edges[:] = [
                    e
                    for e in validated_edges
                    if e["source"] not in unreachable and e["target"] not in unreachable
                ]
                validated_nodes[:] = [n for n in validated_nodes if n["id"] not in unreachable]

        # Determine terminal nodes: explicit list, or nodes with no outgoing edges.
        # Sub-agent nodes are leaf helpers, not endpoints — exclude them.
        sa_ids: set[str] = set()
        for n in validated_nodes:
            for sa_id in n.get("sub_agents") or []:
                sa_ids.add(sa_id)
        terminal_ids: set[str] = set(terminal_nodes or []) - sa_ids
        if not terminal_ids:
            sources = {e["source"] for e in validated_edges}
            all_ids = {n["id"] for n in validated_nodes}
            terminal_ids = all_ids - sources - sa_ids
            # If all nodes have outgoing edges (loop graph), mark the last as terminal
            if not terminal_ids and validated_nodes:
                terminal_ids = {validated_nodes[-1]["id"]}

        # Classify each node into a flowchart component type with color
        total = len(validated_nodes)
        for i, node in enumerate(validated_nodes):
            fc_type = classify_flowchart_node(
                node,
                i,
                total,
                validated_edges,
                terminal_ids,
            )
            fc_meta = FLOWCHART_TYPES[fc_type]
            node["flowchart_type"] = fc_type
            node["flowchart_shape"] = fc_meta["shape"]
            node["flowchart_color"] = fc_meta["color"]

        draft = {
            "agent_name": agent_name.strip(),
            "goal": goal.strip(),
            "description": description.strip(),
            "success_criteria": success_criteria or [],
            "constraints": constraints or [],
            "nodes": validated_nodes,
            "edges": validated_edges,
            "entry_node": validated_nodes[0]["id"] if validated_nodes else "",
            "terminal_nodes": sorted(terminal_ids),
            # Color legend for the frontend
            "flowchart_legend": {
                fc_type: {"shape": meta["shape"], "color": meta["color"]}
                for fc_type, meta in FLOWCHART_TYPES.items()
            },
        }

        bus = getattr(session, "event_bus", None)
        is_building = phase_state is not None and phase_state.phase == "building"

        if phase_state is not None:
            if is_building:
                # During building: re-draft updates the flowchart in place.
                # Dissolve planning-only nodes immediately (no confirm gate).
                import copy as _copy

                phase_state.original_draft_graph = _copy.deepcopy(draft)
                converted, fmap = _dissolve_planning_nodes(draft)
                phase_state.draft_graph = converted
                phase_state.flowchart_map = fmap
                # Do NOT reset build_confirmed — we're already building.
                # Persist to agent folder
                save_path = getattr(session, "worker_path", None)
                if save_path is None:
                    # Worker not loaded yet — resolve from draft name
                    draft_name = draft.get("agent_name", "")
                    if draft_name:
                        from framework.config import COLONIES_DIR

                        candidate = COLONIES_DIR / draft_name
                        if candidate.is_dir():
                            save_path = candidate
                save_flowchart_file(
                    save_path,
                    phase_state.original_draft_graph,
                    fmap,
                )
            else:
                # During planning: store raw draft, await user confirmation.
                phase_state.draft_graph = draft
                phase_state.build_confirmed = False

        # Emit events so the frontend can render
        if bus is not None:
            if is_building:
                await bus.publish(
                    AgentEvent(
                        type=EventType.CUSTOM,
                        stream_id="queen",
                        data={
                            "event": "draft_updated",
                            **(phase_state.draft_graph if phase_state else draft),
                        },
                    )
                )
                await bus.publish(
                    AgentEvent(
                        type=EventType.CUSTOM,
                        stream_id="queen",
                        data={
                            "event": "flowchart_updated",
                            "map": phase_state.flowchart_map if phase_state else None,
                            "original_draft": phase_state.original_draft_graph
                            if phase_state
                            else draft,
                        },
                    )
                )
            else:
                await bus.publish(
                    AgentEvent(
                        type=EventType.CUSTOM,
                        stream_id="queen",
                        data={"event": "draft_updated", **draft},
                    )
                )

        dissolution_info = {}
        if is_building and phase_state is not None and phase_state.original_draft_graph:
            orig_count = len(phase_state.original_draft_graph.get("nodes", []))
            conv_count = len(phase_state.draft_graph.get("nodes", []))
            dissolution_info = {
                "planning_nodes_dissolved": orig_count - conv_count,
                "flowchart_map": phase_state.flowchart_map,
            }

        correction_warning = ""
        if topology_corrections:
            correction_warning = (
                " WARNING — your draft had topology errors that were "
                "auto-corrected: "
                + "; ".join(topology_corrections)
                + " Review the corrected flowchart and do NOT repeat "
                "this pattern. GCU nodes are ALWAYS leaf sub-agents."
            )

        if is_building:
            msg = (
                "Draft flowchart updated during building. "
                "Planning-only nodes dissolved automatically. "
                "The user can see the updated flowchart. "
                "Continue building — no re-confirmation needed." + correction_warning
            )
        else:
            msg = (
                "Draft graph saved and sent to the visualizer. "
                "The user can now see the color-coded flowchart. "
                "Present this design to the user and get their approval. "
                "When the user confirms, call confirm_and_build() to proceed." + correction_warning
            )

        result: dict = {
            "status": "draft_saved",
            "agent_name": draft["agent_name"],
            "node_count": len(validated_nodes),
            "edge_count": len(validated_edges),
            "node_types": {n["id"]: n["flowchart_type"] for n in validated_nodes},
            **dissolution_info,
            "message": msg,
        }
        if topology_corrections:
            result["topology_corrections"] = topology_corrections
        return json.dumps(result)

    _draft_tool = Tool(
        name="save_agent_draft",
        description=(
            "Save a declarative draft of the agent graph as a color-coded flowchart. "
            "Usable in PLANNING (creates draft for user review) and BUILDING "
            "(updates the flowchart in place — planning-only nodes are dissolved "
            "automatically without re-confirmation). "
            "Each node is auto-classified into a classical flowchart type "
            "(start, terminal, process, decision, io, subprocess, browser, manual) "
            "with unique colors. No code is generated. "
            "Planning-only types (decision, browser/GCU) are dissolved at confirm/build time: "
            "decision nodes merge into predecessor's success_criteria with yes/no edges; "
            "browser/GCU nodes merge into predecessor's sub_agents list as leaf delegates."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Snake_case name for the agent (e.g. 'research_agent')",
                },
                "goal": {
                    "type": "string",
                    "description": "High-level goal description for the agent",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what the agent does",
                },
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Kebab-case node identifier"},
                            "name": {"type": "string", "description": "Human-readable name"},
                            "description": {
                                "type": "string",
                                "description": "What this node does (business logic)",
                            },
                            "node_type": {
                                "type": "string",
                                "enum": ["event_loop", "gcu"],
                                "description": "Node type (default: event_loop)",
                            },
                            "flowchart_type": {
                                "type": "string",
                                "enum": [
                                    "start",
                                    "terminal",
                                    "process",
                                    "decision",
                                    "io",
                                    "document",
                                    "database",
                                    "subprocess",
                                    "browser",
                                ],
                                "description": (
                                    "Flowchart symbol type. Auto-detected if omitted. "
                                    "start (sage green stadium), terminal (dusty red stadium), "
                                    "process (blue-gray rect), decision (amber diamond), "
                                    "io (purple parallelogram), document (steel blue wavy rect), "
                                    "database (teal cylinder), subprocess (cyan subroutine), "
                                    "browser (deep blue hexagon — for GCU/browser "
                                    "sub-agents; must be a leaf node)"
                                ),
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Planned tools (hints, not validated yet)",
                            },
                            "input_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Expected input buffer keys (hints)",
                            },
                            "output_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Expected output buffer keys (hints)",
                            },
                            "success_criteria": {
                                "type": "string",
                                "description": "What success looks like for this node",
                            },
                            "sub_agents": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "IDs of GCU/browser sub-agent nodes managed by this node. "
                                    "At build time, sub-agent nodes are dissolved into this list. "
                                    "Set this on the PARENT node — e.g. the orchestrator that "
                                    "delegates to GCU leaves. Visual delegation edges are "
                                    "synthesized automatically."
                                ),
                            },
                            "decision_clause": {
                                "type": "string",
                                "description": (
                                    "For decision nodes only: the yes/no question to "
                                    "evaluate (e.g. 'Is amount > $100?'). Used during "
                                    "dissolution to set the predecessor's success_criteria."
                                ),
                            },
                        },
                        "required": ["id"],
                    },
                    "description": "List of nodes with at minimum an id",
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "condition": {
                                "type": "string",
                                "enum": [
                                    "always",
                                    "on_success",
                                    "on_failure",
                                    "conditional",
                                    "llm_decide",
                                ],
                            },
                            "description": {"type": "string"},
                            "label": {
                                "type": "string",
                                "description": (
                                    "Short edge label shown on the flowchart "
                                    "(e.g. 'Yes', 'No', 'Retry')"
                                ),
                            },
                        },
                        "required": ["source", "target"],
                    },
                    "description": "Connections between nodes",
                },
                "terminal_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Node IDs that are terminal (end) nodes. "
                        "Auto-detected from edges if omitted."
                    ),
                },
                "success_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent-level success criteria",
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent-level constraints",
                },
            },
            "required": ["agent_name", "goal", "nodes"],
        },
    )
    registry.register(
        "save_agent_draft",
        _draft_tool,
        lambda inputs: save_agent_draft(**inputs),
    )
    tools_registered += 1

    # --- confirm_and_build (Planning → Building gate) -------------------------
    # Explicit user confirmation is required before transitioning from planning
    # to building. This tool records that confirmation and proceeds.

    async def confirm_and_build(*, agent_name: str | None = None) -> str:
        """Confirm the draft, create agent directory, and transition to building.

        This tool should ONLY be called after the user has explicitly approved
        the draft graph design via ask_user. It creates the agent directory and
        transitions to BUILDING phase. The queen then writes agent.json directly.
        """
        if phase_state is None:
            return json.dumps({"error": "Phase state not available."})

        if phase_state.phase != "planning":
            return json.dumps(
                {"error": f"Cannot confirm_and_build: currently in {phase_state.phase} phase."}
            )

        if phase_state.draft_graph is None:
            return json.dumps(
                {
                    "error": (
                        "No draft graph saved. Call save_agent_draft() first to create "
                        "a draft, present it to the user, and get their approval."
                    )
                }
            )

        phase_state.build_confirmed = True

        # Preserve original draft for flowchart display during runtime,
        # then dissolve planning-only nodes (decision + browser/GCU) into
        # runtime-compatible structures.
        import copy as _copy

        original_nodes = phase_state.draft_graph.get("nodes", [])
        # Compute dissolution first, then assign all three atomically so that
        # a failure in _dissolve_planning_nodes doesn't leave partial state.
        original_copy = _copy.deepcopy(phase_state.draft_graph)
        converted, fmap = _dissolve_planning_nodes(phase_state.draft_graph)
        phase_state.original_draft_graph = original_copy
        phase_state.draft_graph = converted
        phase_state.flowchart_map = fmap

        # Create agent folder early so flowchart and agent_path are available
        # throughout the entire BUILDING phase.
        _agent_name = agent_name or phase_state.draft_graph.get("agent_name", "").strip()
        if _agent_name:
            from framework.config import COLONIES_DIR

            _agent_folder = COLONIES_DIR / _agent_name
            _agent_folder.mkdir(parents=True, exist_ok=True)
            save_flowchart_file(_agent_folder, original_copy, fmap)
            phase_state.agent_path = str(_agent_folder)
            _update_meta_json(
                session_manager,
                manager_session_id,
                {
                    "agent_path": str(_agent_folder),
                    "agent_name": _agent_name.replace("_", " ").title(),
                },
            )

        dissolved_count = len(original_nodes) - len(converted.get("nodes", []))
        decision_count = sum(1 for n in original_nodes if n.get("flowchart_type") == "decision")
        subagent_count = sum(
            1
            for n in original_nodes
            if n.get("flowchart_type") == "browser" or n.get("node_type") == "gcu"
        )

        dissolution_parts = []
        if decision_count:
            dissolution_parts.append(
                f"{decision_count} decision node(s) dissolved into predecessor criteria"
            )
        if subagent_count:
            dissolution_parts.append(
                f"{subagent_count} sub-agent node(s) dissolved into predecessor sub_agents"
            )

        # Transition to BUILDING phase
        await phase_state.switch_to_building(source="tool")
        _update_meta_json(session_manager, manager_session_id, {"phase": "building"})
        phase_state.build_confirmed = False

        # No injection here -- the return message tells the queen what to do.
        # Injecting would queue a BUILDING message that drains AFTER the queen
        # may have already moved to STAGING via load_built_agent.

        return json.dumps(
            {
                "status": "confirmed",
                "phase": "building",
                "agent_name": _agent_name,
                "agent_path": str(_agent_folder),
                "planning_nodes_dissolved": dissolved_count,
                "flowchart_map": fmap,
                "message": (
                    "Design confirmed and directory created. "
                    + ("; ".join(dissolution_parts) + ". " if dissolution_parts else "")
                    + f"Now write the complete agent config to {_agent_folder}/agent.json "
                    "using write_file(). Include all system prompts, tools, edges, and goal."
                ),
            }
        )

    _confirm_tool = Tool(
        name="confirm_and_build",
        description=(
            "Confirm the draft graph design, create agent directory, and transition to building phase. "
            "ONLY call this after the user has explicitly approved the design via ask_user. "
            "After confirmation, write the complete agent.json using write_file()."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Snake_case name for the agent (e.g. 'linkedin_outreach'). "
                    "If omitted, uses the name from save_agent_draft().",
                },
            },
        },
    )
    registry.register(
        "confirm_and_build",
        _confirm_tool,
        lambda inputs: confirm_and_build(
            agent_name=inputs.get("agent_name"),
        ),
    )
    tools_registered += 1

    # --- stop_worker (Running → Staging) --------------------------------------

    async def stop_worker_to_staging() -> str:
        """Stop the running graph and switch to staging phase.

        After stopping, ask the user whether they want to:
        1. Re-run the agent with new input → call run_agent_with_input(task)
        2. Edit the agent code → call stop_worker_and_review() to go to building phase
        """
        stop_result = await stop_worker()

        # Switch to staging phase
        if phase_state is not None:
            await phase_state.switch_to_staging()
            _update_meta_json(session_manager, manager_session_id, {"phase": "staging"})

        result = json.loads(stop_result)
        result["phase"] = "staging"
        result["message"] = (
            "Graph stopped. You are now in staging phase. "
            "Ask the user: would they like to re-run with new input, "
            "or edit the agent code?"
        )
        return json.dumps(result)

    _stop_worker_tool = Tool(
        name="stop_worker",
        description=(
            "Stop the running graph and switch to staging phase. "
            "After stopping, ask the user whether they want to re-run "
            "with new input or edit the agent code."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("stop_worker", _stop_worker_tool, lambda inputs: stop_worker_to_staging())
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
        completed_ids = {
            evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")
        }
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
                f"Tokens: {len(llm_events)} LLM turns, "
                f"{total_tok:,} total ({total_in:,} in + {total_out:,} out)."
            )

        # Execution outcomes
        exec_completed = bus.get_history(event_type=EventType.EXECUTION_COMPLETED, limit=5)
        exec_failed = bus.get_history(event_type=EventType.EXECUTION_FAILED, limit=5)
        completed_n = len(exec_completed)
        failed_n = len(exec_failed)
        active_n = len(runtime.get_active_streams())
        lines.append(
            f"Executions: {completed_n} completed, {failed_n} failed"
            + (f" ({active_n} active)." if active_n else ".")
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
        completed_ids = {
            evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")
        }
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
                return (
                    f"Worker is {preamble['status']}. "
                    "EventBus unavailable — only basic status returned."
                )

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
                return (
                    f"Unknown focus '{focus}'. "
                    "Valid options: activity, memory, tools, issues, progress, full."
                )
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
                    "description": (
                        "Recent events per category (default 20). Only for activity, tools, full."
                    ),
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
                    resolved_provider = (
                        (spec.credential_id or credential_id) if spec else credential_id
                    )
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
                    "last_validated": (
                        info.last_validated.isoformat() if info.last_validated else None
                    ),
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
                        "Filter to a specific credential type (e.g. 'brave_search'). "
                        "Omit to list all credentials."
                    ),
                },
            },
            "required": [],
        },
    )
    registry.register(
        "list_credentials", _list_creds_tool, lambda inputs: list_credentials(**inputs)
    )
    tools_registered += 1

    # --- load_built_agent (server context only) --------------------------------

    if session_manager is not None and manager_session_id is not None:

        async def load_built_agent(agent_path: str) -> str:
            """Load a newly built agent as the worker in this session.

            After building and validating an agent, call this to make it
            available immediately. The user will see the agent's graph and
            can interact with it without opening a new tab.
            """
            runtime = _get_runtime()
            if runtime is not None:
                try:
                    await session_manager.unload_colony(manager_session_id)
                except Exception as e:
                    logger.error("Failed to unload existing graph: %s", e, exc_info=True)
                    return json.dumps({"error": f"Failed to unload existing graph: {e}"})

            try:
                resolved_path = validate_agent_path(agent_path)
            except ValueError as e:
                return json.dumps({"error": str(e)})
            if not resolved_path.exists():
                return json.dumps({"error": f"Agent path does not exist: {agent_path}"})

            # Pre-check: verify the agent can be loaded before attempting
            # the full session load.  Declarative (agent.json) agents skip
            # the Python import check since AgentRunner.load() handles them.
            _has_yaml = (resolved_path / "agent.json").exists()
            if not _has_yaml:
                # Legacy Python agent: verify module exports goal/nodes/edges
                try:
                    import importlib
                    import sys as _sys

                    pkg_name = resolved_path.name
                    parent_dir = str(resolved_path.resolve().parent)
                    if parent_dir not in _sys.path:
                        _sys.path.insert(0, parent_dir)
                    stale = [
                        n for n in _sys.modules if n == pkg_name or n.startswith(f"{pkg_name}.")
                    ]
                    for n in stale:
                        del _sys.modules[n]

                    mod = importlib.import_module(pkg_name)
                    missing_attrs = [
                        attr
                        for attr in ("goal", "nodes", "edges")
                        if getattr(mod, attr, None) is None
                    ]
                    if missing_attrs:
                        return json.dumps(
                            {
                                "error": (
                                    f"Agent module '{pkg_name}' is missing module-level "
                                    f"attributes: {', '.join(missing_attrs)}. "
                                    f"Fix: in {pkg_name}/__init__.py, add "
                                    f"'from .agent import {', '.join(missing_attrs)}' "
                                    f"so that 'import {pkg_name}' exposes them at "
                                    f"package level."
                                )
                            }
                        )
                except Exception as pre_err:
                    return json.dumps(
                        {
                            "error": (
                                f"Failed to import agent module "
                                f"'{resolved_path.name}': {pre_err}. "
                                f"Fix: ensure {resolved_path.name}/__init__.py "
                                f"exists and can be imported without errors "
                                f"(check syntax, missing dependencies, and "
                                f"relative imports)."
                            )
                        }
                    )

            try:
                updated_session = await session_manager.load_colony(
                    manager_session_id,
                    str(resolved_path),
                )
                info = updated_session.worker_info

                # Tools declared but not registered in the loaded runtime are
                # stripped with a warning so the worker still starts. Forked
                # workers often snapshot the queen's tool list which includes
                # MCP tools the worker's runtime doesn't load; blocking on
                # that would leave the queen stranded.
                loaded_runtime = _get_runtime()
                if loaded_runtime is not None:
                    available_tool_names = {t.name for t in loaded_runtime._tools}
                    for node in loaded_runtime.graph.nodes:
                        if node.tools:
                            declared = list(node.tools)
                            kept = [t for t in declared if t in available_tool_names]
                            missing = [t for t in declared if t not in available_tool_names]
                            if missing:
                                logger.warning(
                                    "Node '%s' (id=%s) declares %d tools not in the "
                                    "loaded runtime; stripping and continuing: %s",
                                    node.name,
                                    node.id,
                                    len(missing),
                                    sorted(missing),
                                )
                                node.tools = kept

                # Ensure we have a flowchart for this agent — try in order:
                # 1. Already in phase_state (from planning workflow)
                # 2. Load from flowchart.json in the agent folder
                # 3. Synthesize from the runtime graph
                if phase_state is not None:
                    if phase_state.original_draft_graph is None:
                        # Try loading from file
                        file_draft, file_map = load_flowchart_file(resolved_path)
                        if file_draft is not None:
                            phase_state.original_draft_graph = file_draft
                            phase_state.flowchart_map = file_map
                        elif loaded_runtime is not None:
                            # Synthesize from runtime graph
                            goal = loaded_runtime.goal
                            synth_draft, synth_map = synthesize_draft_from_runtime(
                                list(loaded_runtime.graph.nodes),
                                list(loaded_runtime.graph.edges),
                                agent_name=resolved_path.name,
                                goal_name=goal.name if goal else "",
                            )
                            phase_state.original_draft_graph = synth_draft
                            phase_state.flowchart_map = synth_map
                            # Persist the synthesized flowchart so it's
                            # available on next load without re-synthesis
                            save_flowchart_file(resolved_path, synth_draft, synth_map)

                    # Emit to frontend
                    if (
                        phase_state.original_draft_graph is not None
                        and phase_state.flowchart_map is not None
                    ):
                        bus = phase_state.event_bus
                        if bus is not None:
                            try:
                                await bus.publish(
                                    AgentEvent(
                                        type=EventType.CUSTOM,
                                        stream_id="queen",
                                        data={
                                            "event": "flowchart_updated",
                                            "map": phase_state.flowchart_map,
                                            "original_draft": phase_state.original_draft_graph,
                                        },
                                    )
                                )
                            except Exception:
                                logger.warning("Failed to emit flowchart map", exc_info=True)

                # Switch to staging phase after successful load + validation
                if phase_state is not None:
                    phase_state.agent_path = str(resolved_path)
                    await phase_state.switch_to_staging()
                    _update_meta_json(session_manager, manager_session_id, {"phase": "staging"})

                graph_name = info.name if info else updated_session.colony_id
                return json.dumps(
                    {
                        "status": "loaded",
                        "phase": "staging",
                        "message": (
                            f"Successfully loaded '{graph_name}'. "
                            "You are now in STAGING phase. "
                            "Call run_agent_with_input(task) to start the graph, "
                            "or stop_worker_and_review() to go back to building."
                        ),
                        "colony_id": updated_session.colony_id,
                        "graph_name": graph_name,
                        "goal": info.goal_name if info else "",
                        "node_count": info.node_count if info else 0,
                    }
                )
            except Exception as e:
                logger.error("load_built_agent failed for '%s'", agent_path, exc_info=True)
                return json.dumps({"error": f"Failed to load agent: {e}"})

        _load_built_tool = Tool(
            name="load_built_agent",
            description=(
                "Load a newly built agent as the worker in this session. "
                "After building and validating an agent, call this with the agent's "
                "path (e.g. '~/.hive/colonies/my_agent') to make it available immediately. "
                "The user will see the agent's graph and can interact with it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_path": {
                        "type": "string",
                        "description": (
                            "Path to the agent directory (e.g. '~/.hive/colonies/my_agent')"
                        ),
                    },
                },
                "required": ["agent_path"],
            },
        )
        registry.register(
            "load_built_agent",
            _load_built_tool,
            lambda inputs: load_built_agent(**inputs),
        )
        tools_registered += 1

    # --- run_agent_with_input ------------------------------------------------

    async def run_agent_with_input(task: str) -> str:
        """Run the loaded worker agent with the given task input.

        Phase 4 unified path: spawns the loaded worker through
        ``session.colony.spawn(...)`` (a real ColonyRuntime) instead of
        the deprecated ``AgentHost.trigger`` → ``Orchestrator`` flow.
        The new path passes ``input_data={"user_request": task}``
        straight into ``AgentLoop._build_initial_message`` which
        renders ALL keys to the worker's first user message — no
        buffer filter, no dropped task string, no orchestrator
        graph-execution machinery.

        We still read the legacy ``session.colony_runtime`` (the
        AgentHost loaded by ``load_built_agent``) to pull the worker's
        tool list, tool executor, and entry-node system prompt — those
        are the loaded honeycomb / custom worker's actual identity and
        we want the spawned worker to BE that, not the queen's generic
        colony spec.
        """
        legacy = _get_runtime()  # the loaded AgentHost from load_built_agent
        if legacy is None:
            return json.dumps({"error": "No worker loaded in this session."})

        colony = getattr(session, "colony", None)
        if colony is None:
            return json.dumps(
                {
                    "error": (
                        "Session has no unified ColonyRuntime — "
                        "_start_unified_colony_runtime did not run. "
                        "Cannot spawn worker."
                    )
                }
            )

        # Diagnostic: log the exact task arg the queen passed so we can
        # spot generic / context-free task strings before they reach
        # the worker. The worker has no chat context, so a vague task
        # is the #1 cause of useless worker runs.
        logger.info(
            "run_agent_with_input: queen passing task to worker (len=%d): %r",
            len(task),
            task[:500] if isinstance(task, str) else task,
        )
        if isinstance(task, str) and len(task) < 60:
            logger.warning(
                "run_agent_with_input: SHORT TASK STRING (%d chars). "
                "The worker has zero context from the queen's chat — "
                "tasks shorter than ~60 chars usually fail because "
                "they lack the specific instructions the worker needs. "
                "Task: %r",
                len(task),
                task,
            )

        try:
            # Pre-flight: compute the set of tools whose credentials are
            # NOT currently available, and resync MCP servers. We do NOT
            # hard-fail on missing credentials anymore — instead we drop
            # the affected tools from the worker's spawn_tools list a
            # few lines below. Hard-failing here caused unrelated tools
            # (e.g. GitHub tools leaking into a LinkedIn worker config)
            # to block the whole spawn with a CredentialError; the fix
            # is to treat unset credentials as "drop these tools" rather
            # than "abort the worker".
            #
            # Note: the MCP admission gate (_build_mcp_admission_gate in
            # tool_registry.py) already filters MCP tools at registration
            # time. This preflight covers the non-MCP path — tools.py
            # discoveries via discover_from_module — which has no
            # credential gate of its own.
            loop = asyncio.get_running_loop()
            unavailable_tools: set[str] = set()

            async def _preflight():
                nonlocal unavailable_tools
                try:
                    from framework.credentials.validation import compute_unavailable_tools

                    drop, messages = await loop.run_in_executor(
                        None,
                        lambda: compute_unavailable_tools(legacy.graph.nodes),
                    )
                    unavailable_tools = drop
                    if drop:
                        logger.warning(
                            "run_agent_with_input: dropping %d tool(s) with "
                            "unavailable credentials from worker spawn: %s",
                            len(drop),
                            "; ".join(messages),
                        )
                except Exception as exc:
                    # Validation itself failing (not a credential failure —
                    # a code error in the validator) should not block the
                    # spawn. Log and proceed as if nothing was dropped.
                    logger.warning(
                        "compute_unavailable_tools raised, proceeding without "
                        "credential-based tool filtering: %s",
                        exc,
                    )

                runner = getattr(session, "runner", None)
                if runner:
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda: runner._tool_registry.resync_mcp_servers_if_needed(),
                        )
                    except Exception as e:
                        logger.warning("MCP resync failed: %s", e)

            try:
                await asyncio.wait_for(_preflight(), timeout=_START_PREFLIGHT_TIMEOUT)
            except TimeoutError:
                logger.warning(
                    "run_agent_with_input preflight timed out after %ds — proceeding",
                    _START_PREFLIGHT_TIMEOUT,
                )

            # Build a per-spawn AgentSpec that mirrors the loaded
            # worker's entry-node identity. This is what makes the
            # spawned ColonyRuntime worker run the loaded honeycomb /
            # custom worker's code instead of the queen's generic
            # colony default.
            from framework.agent_loop.types import AgentSpec

            graph = getattr(legacy, "graph", None)
            entry_node = None
            if graph is not None and hasattr(graph, "get_node"):
                try:
                    entry_node = graph.get_node(graph.entry_node)
                except Exception:
                    entry_node = None

            worker_system_prompt = (
                getattr(entry_node, "system_prompt", None)
                if entry_node is not None
                else None
            ) or ""

            worker_tool_names = (
                list(getattr(entry_node, "tools", []) or [])
                if entry_node is not None
                else []
            )

            # Drop any tool whose credential isn't available (GitHub
            # tools when GITHUB_TOKEN is unset, etc). The preflight
            # above populated ``unavailable_tools``; apply the filter
            # HERE — before the AgentSpec is built — so the worker
            # only sees tools it can actually run.
            dropped_from_names: list[str] = []
            if unavailable_tools:
                original = worker_tool_names
                worker_tool_names = [t for t in original if t not in unavailable_tools]
                dropped_from_names = [t for t in original if t in unavailable_tools]
                if dropped_from_names:
                    logger.warning(
                        "run_agent_with_input: dropped %d tool(s) from worker "
                        "AgentSpec due to unavailable credentials: %s",
                        len(dropped_from_names),
                        ", ".join(dropped_from_names),
                    )

            spawn_spec = AgentSpec(
                id=f"loaded_worker:{getattr(graph, 'id', 'unknown')}",
                name=getattr(graph, "id", "loaded_worker"),
                description=(
                    "Loaded worker agent spawned via run_agent_with_input "
                    "through the unified ColonyRuntime path."
                ),
                system_prompt=worker_system_prompt,
                tools=worker_tool_names,
                tool_access_policy="all",
            )

            # Pull the live tool objects + executor straight from the
            # loaded AgentHost so the spawned worker uses its actual
            # MCP-loaded tools (browser, hubspot, honeycomb, etc.).
            spawn_tools = list(getattr(legacy, "_tools", []) or [])
            spawn_tool_executor = getattr(legacy, "_tool_executor", None)

            # Same credential-based filter on the live Tool objects
            # passed to the worker. Without this the worker would still
            # receive the GitHub tool definitions in its registry —
            # it just wouldn't see them in its AgentSpec, so the LLM
            # wouldn't know to use them. Dropping from both lists
            # makes the filter complete.
            if unavailable_tools:
                before = len(spawn_tools)
                spawn_tools = [
                    t for t in spawn_tools
                    if getattr(t, "name", None) not in unavailable_tools
                ]
                dropped_count = before - len(spawn_tools)
                if dropped_count:
                    logger.info(
                        "run_agent_with_input: dropped %d tool object(s) from "
                        "spawn_tools (unavailable credentials)",
                        dropped_count,
                    )

            # Colony progress tracker wiring: if the loaded worker
            # lives under ~/.hive/colonies/{name}/ and has a
            # progress.db, inject db_path + colony_id into input_data
            # so the spawned worker sees them in its first user
            # message and can use the hive.colony-progress-tracker
            # skill to claim tasks from the queue.
            _spawn_input_data: dict[str, Any] = {"user_request": task}
            _worker_path = getattr(session, "worker_path", None)
            if _worker_path:
                from pathlib import Path as _Path

                _worker_path_p = _Path(_worker_path)
                _progress_db = _worker_path_p / "data" / "progress.db"
                if _progress_db.exists():
                    _spawn_input_data["db_path"] = str(_progress_db.resolve())
                    _spawn_input_data["colony_id"] = _worker_path_p.name
                    logger.info(
                        "run_agent_with_input: attached progress_db context "
                        "(colony_id=%s, db_path=%s)",
                        _worker_path_p.name,
                        _progress_db,
                    )

                    # Phase 2: enqueue the task into progress.db BEFORE
                    # spawning so the worker has a concrete row to
                    # claim. Without this the queue is empty and the
                    # worker's claim UPDATE affects zero rows, so it
                    # silently falls back to executing from the chat
                    # spawn message. Any enqueue failure is logged and
                    # the spawn proceeds without a pinned task_id
                    # (degrades to the pre-Phase-2 behavior).
                    try:
                        from framework.host.progress_db import (
                            enqueue_task as _enqueue_task_fn,
                        )

                        _task_id = await asyncio.to_thread(
                            _enqueue_task_fn,
                            _progress_db,
                            task,
                            source="run_agent_with_input",
                        )
                        _spawn_input_data["task_id"] = _task_id
                        logger.info(
                            "run_agent_with_input: enqueued task %s into %s",
                            _task_id,
                            _progress_db,
                        )
                    except Exception as _enqueue_exc:
                        logger.warning(
                            "run_agent_with_input: failed to enqueue task "
                            "into progress.db (spawn proceeding without "
                            "pinned task_id): %s",
                            _enqueue_exc,
                        )

            worker_ids = await colony.spawn(
                task=task,
                count=1,
                input_data=_spawn_input_data,
                agent_spec=spawn_spec,
                tools=spawn_tools,
                tool_executor=spawn_tool_executor,
                # Use the legacy single-worker stream tag so events flow
                # through the SSE filter into the queen DM chat. The
                # default "worker:{uuid}" tag is reserved for parallel
                # fan-out via run_parallel_workers and is filtered out
                # of the queen DM by routes_events.py to keep the chat
                # clean. The loaded primary worker is the user's
                # main visible workstream and must NOT be filtered.
                stream_id="worker",
            )
            new_worker_id = worker_ids[0] if worker_ids else ""

            # Switch to running phase
            if phase_state is not None:
                await phase_state.switch_to_running()
                _update_meta_json(session_manager, manager_session_id, {"phase": "running"})

            return json.dumps(
                {
                    "status": "started",
                    "phase": "running",
                    "worker_id": new_worker_id,
                    "task": task,
                    "tool_count": len(spawn_tools),
                    "system_prompt_chars": len(worker_system_prompt),
                }
            )
        except CredentialError as e:
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
        except Exception as e:
            logger.exception("run_agent_with_input: spawn failed")
            return json.dumps({"error": f"Failed to start worker: {e}"})

    _run_input_tool = Tool(
        name="run_agent_with_input",
        description=(
            "Run the loaded worker agent with the given task.\n\n"
            "CRITICAL: the worker is a FRESH process. It has NO memory of "
            "your conversation with the user, NO knowledge of what was "
            "discussed, and NO access to your context. It only sees the "
            "single 'task' string you pass here. If the user asked you "
            "to fetch '125 tickers and build a market report with "
            "gainers, losers, and category breakdowns', that ENTIRE "
            "specification must be in the task arg verbatim — not "
            "'continue our work', not 'do what we discussed', not "
            "'finish the analysis'. Bad task: 'Continue the work from "
            "the queen's current session'. Good task: 'Fetch all 125 "
            "tickers from the honeycomb API (paginate past the default "
            "50 page limit), then build a full market report including: "
            "(1) top 10 gainers by % change, (2) top 10 losers, (3) top "
            "10 by volume, (4) breakdown by category, (5) any unusual "
            "patterns. Return as a structured summary.' Validates "
            "credentials and switches to running phase. Use this after "
            "loading an agent (staging phase) to start execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "FULL self-contained task specification for the "
                        "worker. Must include every requirement, "
                        "constraint, and detail the worker needs — the "
                        "worker has zero context from your conversation. "
                        "Write it as if you're handing the task to a "
                        "stranger who has never seen the user's request."
                    ),
                },
            },
            "required": ["task"],
        },
    )
    registry.register(
        "run_agent_with_input", _run_input_tool, lambda inputs: run_agent_with_input(**inputs)
    )
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
                    "error": "Unknown request_id. Call list_worker_questions() "
                    "to see currently pending escalations.",
                    "request_id": request_id,
                }
            )

        worker_id = entry.get("worker_id")
        if not worker_id:
            return json.dumps(
                {"error": "Escalation entry is missing worker_id.", "request_id": request_id}
            )

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
    registry.register(
        "reply_to_worker", _reply_tool, lambda inputs: reply_to_worker(**inputs)
    )
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
                return json.dumps(
                    {"error": f"Invalid HTTP methods: {invalid}. Valid: {sorted(valid_methods)}"}
                )

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
                return json.dumps(
                    {"error": "croniter package not installed — cannot validate cron expression."}
                )
        elif interval:
            if not isinstance(interval, (int, float)) or interval <= 0:
                return json.dumps({"error": f"interval_minutes must be > 0, got {interval}"})
        else:
            return json.dumps(
                {"error": "Timer trigger needs 'cron' or 'interval_minutes' in trigger_config."}
            )

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
                    "description": (
                        "ID of the trigger to activate (from list_triggers) or a new custom ID"
                    ),
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
        description=(
            "Deactivate an active trigger."
            " The trigger stops firing but remains available for re-activation."
        ),
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
    registry.register(
        "remove_trigger", _remove_trigger_tool, lambda inputs: remove_trigger(**inputs)
    )
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
        description=(
            "List all available triggers (from the loaded worker) and their active/inactive status."
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
    )
    registry.register("list_triggers", _list_triggers_tool, lambda inputs: list_triggers())
    tools_registered += 1

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
