"""Queen lifecycle tools for worker management.

These tools give the Queen agent control over the worker agent's lifecycle.
They close over a session-like object that provides ``worker_runtime``,
allowing late-binding access to the worker (which may be loaded/unloaded
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
        worker_runtime=runtime,
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
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.credentials.models import CredentialError
from framework.runner.preload_validation import credential_errors_to_json, validate_credentials
from framework.runtime.event_bus import AgentEvent, EventType
from framework.server.app import validate_agent_path

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import AgentRuntime
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class WorkerSessionAdapter:
    """Adapter for TUI compatibility.

    Wraps bare worker_runtime + event_bus + storage_path into a
    session-like object that queen lifecycle tools can use.
    """

    worker_runtime: Any  # AgentRuntime
    event_bus: Any  # EventBus
    worker_path: Path | None = None


@dataclass
class QueenPhaseState:
    """Mutable state container for queen operating phase.

    Four phases: planning → building → staging → running.
    Shared between the dynamic_tools_provider callback and tool handlers
    that trigger phase transitions.
    """

    phase: str = "building"  # "planning", "building", "staging", or "running"
    planning_tools: list = field(default_factory=list)  # list[Tool]
    building_tools: list = field(default_factory=list)  # list[Tool]
    staging_tools: list = field(default_factory=list)  # list[Tool]
    running_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_PHASE_CHANGED events

    # Phase-specific prompts (set by session_manager after construction)
    prompt_planning: str = ""
    prompt_building: str = ""
    prompt_staging: str = ""
    prompt_running: str = ""

    def get_current_tools(self) -> list:
        """Return tools for the current phase."""
        if self.phase == "planning":
            return list(self.planning_tools)
        if self.phase == "running":
            return list(self.running_tools)
        if self.phase == "staging":
            return list(self.staging_tools)
        return list(self.building_tools)

    def get_current_prompt(self) -> str:
        """Return the system prompt for the current phase, with fresh memory appended."""
        if self.phase == "planning":
            base = self.prompt_planning
        elif self.phase == "running":
            base = self.prompt_running
        elif self.phase == "staging":
            base = self.prompt_staging
        else:
            base = self.prompt_building

        from framework.agents.queen.queen_memory import format_for_injection

        memory = format_for_injection()
        return base + ("\n\n" + memory if memory else "")

    async def _emit_phase_event(self) -> None:
        """Publish a QUEEN_PHASE_CHANGED event so the frontend updates the tag."""
        if self.event_bus is not None:
            await self.event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_PHASE_CHANGED,
                    stream_id="queen",
                    data={"phase": self.phase},
                )
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

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "building":
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

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "planning":
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


def build_worker_profile(runtime: AgentRuntime, agent_path: Path | str | None = None) -> str:
    """Build a worker capability profile from its graph/goal definition.

    Injected into the queen's system prompt so it knows what the worker
    can and cannot do — enabling correct delegation decisions.
    """
    graph = runtime.graph
    goal = runtime.goal

    lines = ["\n\n# Worker Profile"]
    lines.append(f"Agent: {runtime.graph_id}")
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

    if graph.nodes:
        lines.append("\n## Processing Stages")
        for node in graph.nodes:
            lines.append(f"- {node.id}: {node.description or node.name}")

    all_tools: set[str] = set()
    for node in graph.nodes:
        if node.tools:
            all_tools.update(node.tools)
    if all_tools:
        lines.append(f"\n## Worker Tools\n{', '.join(sorted(all_tools))}")

    lines.append("\nStatus at session start: idle (not started).")
    return "\n".join(lines)


def register_queen_lifecycle_tools(
    registry: ToolRegistry,
    session: Any = None,
    session_id: str | None = None,
    # Legacy params — used by TUI when not passing a session object
    worker_runtime: AgentRuntime | None = None,
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
        session: A Session or WorkerSessionAdapter with ``worker_runtime``
            attribute. The tools read ``session.worker_runtime`` on each
            call, supporting late-binding (worker loaded/unloaded).
        session_id: Shared session ID so the worker uses the same session
            scope as the queen and judge.
        worker_runtime: (Legacy) Direct runtime reference. If ``session``
            is not provided, a WorkerSessionAdapter is created from
            worker_runtime + event_bus + storage_path.
        session_manager: (Server only) The SessionManager instance, needed
            for ``load_built_agent`` to hot-load a worker.
        manager_session_id: (Server only) The session's ID in the manager,
            used with ``session_manager.load_worker()``.
        phase_state: (Optional) Mutable phase state for building/running
            phase switching. When provided, load_built_agent switches to
            running phase and stop_worker_and_edit switches to building phase.

    Returns the number of tools registered.
    """
    # Build session adapter from legacy params if needed
    if session is None:
        if worker_runtime is None:
            raise ValueError("Either session or worker_runtime must be provided")
        session = WorkerSessionAdapter(
            worker_runtime=worker_runtime,
            event_bus=event_bus,
            worker_path=storage_path,
        )

    from framework.llm.provider import Tool

    tools_registered = 0

    def _get_runtime():
        """Get current worker runtime from session (late-binding)."""
        return getattr(session, "worker_runtime", None)

    # --- start_worker ---------------------------------------------------------

    # How long to wait for credential validation + MCP resync before
    # proceeding with trigger anyway.  These are pre-flight checks that
    # should not block the queen indefinitely.
    _START_PREFLIGHT_TIMEOUT = 15  # seconds

    async def start_worker(task: str) -> str:
        """Start the worker agent with a task description.

        Triggers the worker's default entry point with the given task.
        Returns immediately — the worker runs asynchronously.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        try:
            # Pre-flight: validate credentials and resync MCP servers.
            # Both are blocking I/O (HTTP health-checks, subprocess spawns)
            # so they run in a thread-pool executor.  We cap the total
            # preflight time so the queen never hangs waiting.
            loop = asyncio.get_running_loop()

            async def _preflight():
                cred_error: CredentialError | None = None
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: validate_credentials(
                            runtime.graph.nodes,
                            interactive=False,
                            skip=False,
                        ),
                    )
                except CredentialError as e:
                    cred_error = e

                runner = getattr(session, "runner", None)
                if runner:
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda: runner._tool_registry.resync_mcp_servers_if_needed(),
                        )
                    except Exception as e:
                        logger.warning("MCP resync failed: %s", e)

                # Re-raise CredentialError after MCP resync so both steps
                # get a chance to run before we bail.
                if cred_error is not None:
                    raise cred_error

            try:
                await asyncio.wait_for(_preflight(), timeout=_START_PREFLIGHT_TIMEOUT)
            except TimeoutError:
                logger.warning(
                    "start_worker preflight timed out after %ds — proceeding with trigger",
                    _START_PREFLIGHT_TIMEOUT,
                )
            except CredentialError:
                raise  # handled below

            # Resume timers in case they were paused by a previous stop_worker
            runtime.resume_timers()

            # Get session state from any prior execution for memory continuity
            session_state = runtime._get_primary_session_state("default") or {}

            # Use the shared session ID so queen, judge, and worker all
            # scope their conversations to the same session.
            if session_id:
                session_state["resume_session_id"] = session_id

            exec_id = await runtime.trigger(
                entry_point_id="default",
                input_data={"user_request": task},
                session_state=session_state,
            )
            return json.dumps(
                {
                    "status": "started",
                    "execution_id": exec_id,
                    "task": task,
                }
            )
        except CredentialError as e:
            # Build structured error with per-credential details so the
            # queen can report exactly what's missing and how to fix it.
            error_payload = credential_errors_to_json(e)
            error_payload["agent_path"] = str(getattr(session, "worker_path", "") or "")

            # Emit SSE event so the frontend opens the credentials modal
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
            return json.dumps({"error": f"Failed to start worker: {e}"})

    _start_tool = Tool(
        name="start_worker",
        description=(
            "Start the worker agent with a task description. The worker runs "
            "autonomously in the background. Returns an execution ID for tracking."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the worker to perform",
                },
            },
            "required": ["task"],
        },
    )
    registry.register("start_worker", _start_tool, lambda inputs: start_worker(**inputs))
    tools_registered += 1

    # --- stop_worker ----------------------------------------------------------

    async def stop_worker(*, reason: str = "Stopped by queen") -> str:
        """Cancel all active worker executions across all graphs.

        Stops the worker immediately. Returns the IDs of cancelled executions.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        cancelled = []

        # Iterate ALL registered graphs — multiple entrypoint requests
        # can spawn executions in different graphs within the same session.
        for graph_id in runtime.list_graphs():
            reg = runtime.get_graph_registration(graph_id)
            if reg is None:
                continue

            for _ep_id, stream in reg.streams.items():
                # Signal shutdown on all active EventLoopNodes first so they
                # exit cleanly and cancel their in-flight LLM streams.
                for executor in stream._active_executors.values():
                    for node in executor.node_registry.values():
                        if hasattr(node, "signal_shutdown"):
                            node.signal_shutdown()
                        if hasattr(node, "cancel_current_turn"):
                            node.cancel_current_turn()

                for exec_id in list(stream.active_execution_ids):
                    try:
                        ok = await stream.cancel_execution(exec_id, reason=reason)
                        if ok:
                            cancelled.append(exec_id)
                    except Exception as e:
                        logger.warning("Failed to cancel %s: %s", exec_id, e)

        # Pause timers so the next tick doesn't restart execution
        runtime.pause_timers()

        return json.dumps(
            {
                "status": "stopped" if cancelled else "no_active_executions",
                "cancelled": cancelled,
                "timers_paused": True,
            }
        )

    _stop_tool = Tool(
        name="stop_worker",
        description=(
            "Cancel the worker agent's active execution and pause its timers. "
            "The worker stops gracefully. No parameters needed."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("stop_worker", _stop_tool, lambda inputs: stop_worker())
    tools_registered += 1

    # --- stop_worker_and_edit -------------------------------------------------

    async def stop_worker_and_edit() -> str:
        """Stop the worker and switch to building phase for editing the agent."""
        stop_result = await stop_worker()

        # Switch to building phase
        if phase_state is not None:
            await phase_state.switch_to_building()

        result = json.loads(stop_result)
        result["phase"] = "building"
        result["message"] = (
            "Worker stopped. You are now in building phase. "
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
        name="stop_worker_and_edit",
        description=(
            "Stop the running worker and switch to building phase. "
            "Use this when you need to modify the agent's code, nodes, or configuration. "
            "After editing, call load_built_agent(path) to reload and run."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "stop_worker_and_edit", _stop_edit_tool, lambda inputs: stop_worker_and_edit()
    )
    tools_registered += 1

    # --- stop_worker_and_plan (Running/Staging → Planning) --------------------

    async def stop_worker_and_plan() -> str:
        """Stop the worker and switch to planning phase for diagnosis."""
        stop_result = await stop_worker()

        # Switch to planning phase
        if phase_state is not None:
            await phase_state.switch_to_planning(source="tool")

        result = json.loads(stop_result)
        result["phase"] = "planning"
        result["message"] = (
            "Worker stopped. You are now in planning phase. "
            "Diagnose the issue using read-only tools (checkpoints, logs, sessions), "
            "discuss a fix plan with the user, then call "
            "initialize_and_build_agent() to implement the fix."
        )
        return json.dumps(result)

    _stop_plan_tool = Tool(
        name="stop_worker_and_plan",
        description=(
            "Stop the worker and switch to planning phase for diagnosis. "
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
            await phase_state.switch_to_planning(source="tool")
        return json.dumps(
            {
                "status": "replanning",
                "phase": "planning",
                "message": (
                    "Switched to PLANNING phase. Coding tools removed. "
                    "Discuss the new design with the user."
                ),
            }
        )

    _replan_tool = Tool(
        name="replan_agent",
        description=(
            "Switch from building back to planning phase. "
            "Only use when the user explicitly asks to re-plan or redesign the agent."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("replan_agent", _replan_tool, lambda inputs: replan_agent())
    tools_registered += 1

    # --- initialize_and_build_agent wrapper (Planning → Building) -------------
    # With agent_name: scaffold a new agent via MCP tool, then switch to building.
    # Without agent_name: just switch to building (for fixing an existing loaded agent).

    _existing_init = registry._tools.get("initialize_and_build_agent")
    if _existing_init is not None:
        _orig_init_executor = _existing_init.executor

        async def initialize_and_build_agent_wrapper(inputs: dict) -> str:
            """Wrapper: scaffold or just switch to building phase."""
            agent_name = (inputs.get("agent_name") or "").strip()

            # No agent_name → try to fall back to the session's current agent,
            # or fail with actionable guidance.
            if not agent_name:
                # Try to resolve agent_name from the current session
                fallback_path = getattr(session, "worker_path", None)
                if fallback_path is not None:
                    agent_name = Path(fallback_path).name
                else:
                    # Server path: check SessionManager
                    if session_manager is not None and manager_session_id:
                        srv_session = session_manager.get_session(manager_session_id)
                        if srv_session and getattr(srv_session, "worker_path", None):
                            fallback_path = srv_session.worker_path
                            agent_name = Path(fallback_path).name

                if not agent_name:
                    return json.dumps(
                        {
                            "error": (
                                "No agent_name provided and no agent loaded in this session. "
                                "To fix: call list_agents() to find the agent name, then call "
                                "initialize_and_build_agent(agent_name='<name>') to scaffold it."
                            )
                        }
                    )

                # Fall back succeeded — switch to building without scaffolding
                logger.info(
                    "initialize_and_build_agent: no agent_name provided, "
                    "falling back to session agent '%s'",
                    agent_name,
                )
                if phase_state is not None:
                    await phase_state.switch_to_building(source="tool")
                    if phase_state.inject_notification:
                        await phase_state.inject_notification(
                            "[PHASE CHANGE] Switched to BUILDING phase. "
                            "Start implementing the fix now."
                        )
                return json.dumps(
                    {
                        "status": "editing",
                        "phase": "building",
                        "agent_name": agent_name,
                        "warning": (
                            f"No agent_name provided — using session agent '{agent_name}'. "
                            f"Agent files are at exports/{agent_name}/."
                        ),
                        "message": (
                            "Switched to BUILDING phase. Full coding tools restored. "
                            "Implement the fix, then call load_built_agent(path) to reload."
                        ),
                    }
                )

            # Has agent_name → scaffold via MCP tool
            result = _orig_init_executor(inputs)
            # Handle both sync and async executors
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                result = await result
            # If result is a ToolResult, extract the text content
            result_str = str(result)
            if hasattr(result, "content"):
                result_str = str(result.content)
            try:
                parsed = json.loads(result_str)
                if parsed.get("success", True):
                    if phase_state is not None:
                        await phase_state.switch_to_building(source="tool")
                        # Inject a continuation message so the queen starts
                        # building immediately instead of blocking for user input.
                        if phase_state.inject_notification:
                            await phase_state.inject_notification(
                                "[PHASE CHANGE] Agent scaffolded and switched to BUILDING phase. "
                                "Start implementing the agent nodes now."
                            )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
            return result_str

        registry.register(
            "initialize_and_build_agent",
            _existing_init.tool,
            lambda inputs: initialize_and_build_agent_wrapper(inputs),
        )

    # --- stop_worker (Running → Staging) -------------------------------------

    async def stop_worker_to_staging() -> str:
        """Stop the running worker and switch to staging phase.

        After stopping, ask the user whether they want to:
        1. Re-run the agent with new input → call run_agent_with_input(task)
        2. Edit the agent code → call stop_worker_and_edit() to go to building phase
        """
        stop_result = await stop_worker()

        # Switch to staging phase
        if phase_state is not None:
            await phase_state.switch_to_staging()

        result = json.loads(stop_result)
        result["phase"] = "staging"
        result["message"] = (
            "Worker stopped. You are now in staging phase. "
            "Ask the user: would they like to re-run with new input, "
            "or edit the agent code?"
        )
        return json.dumps(result)

    _stop_worker_tool = Tool(
        name="stop_worker",
        description=(
            "Stop the running worker and switch to staging phase. "
            "After stopping, ask the user whether they want to re-run "
            "with new input or edit the agent code."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("stop_worker", _stop_worker_tool, lambda inputs: stop_worker_to_staging())
    tools_registered += 1

    # --- get_worker_status ----------------------------------------------------

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
        from datetime import datetime

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
        runtime: AgentRuntime,
    ) -> dict[str, Any]:
        """Build the lightweight preamble: status, node, elapsed, iteration.

        Always cheap to compute. Returns a dict with:
        - status: idle / running / waiting_for_input
        - current_node, current_iteration, elapsed_seconds (when applicable)
        - pending_question (when waiting)
        - _active_execs (internal, stripped before return)
        """
        from datetime import datetime

        graph_id = runtime.graph_id
        reg = runtime.get_graph_registration(graph_id)
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

            edge_events = bus.get_history(event_type=EventType.EDGE_TRAVERSED, limit=1)
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
        edges = bus.get_history(event_type=EventType.EDGE_TRAVERSED, limit=last_n)
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

    async def _format_memory(runtime: AgentRuntime) -> str:
        """Format the worker's shared memory snapshot and recent changes."""
        from framework.runtime.shared_state import IsolationLevel

        lines = []
        active_streams = runtime.get_active_streams()

        if not active_streams:
            return "Worker has no active executions. No memory to inspect."

        # Read memory from the first active execution
        stream_info = active_streams[0]
        exec_ids = stream_info.get("active_execution_ids", [])
        stream_id = stream_info.get("stream_id", "")
        if not exec_ids:
            return "No active execution found."

        exec_id = exec_ids[0]
        memory = runtime.state_manager.create_memory(exec_id, stream_id, IsolationLevel.SHARED)
        state = await memory.read_all()

        if not state:
            lines.append("Worker's shared memory is empty.")
        else:
            lines.append(f"Worker's shared memory ({len(state)} keys):")
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

    async def _format_progress(runtime: AgentRuntime, bus: EventBus) -> str:
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
        runtime: AgentRuntime,
        bus: EventBus,
        preamble: dict[str, Any],
        last_n: int,
    ) -> dict[str, Any]:
        """Build the legacy full JSON response (backward compat for focus='full')."""

        graph_id = runtime.graph_id
        goal = runtime.goal
        result: dict[str, Any] = {
            "worker_graph_id": graph_id,
            "worker_goal": getattr(goal, "name", graph_id),
            "status": preamble["status"],
        }

        active_execs = preamble.get("_active_execs", [])
        if active_execs:
            result["active_executions"] = active_execs
        if preamble.get("pending_question"):
            result["pending_question"] = preamble["pending_question"]

        result["agent_idle_seconds"] = round(runtime.agent_idle_seconds, 1)

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
            result["recent_tool_calls"] = [
                {
                    "tool": evt.data.get("tool_name"),
                    "error": bool(evt.data.get("is_error")),
                    "node": evt.node_id,
                    "time": evt.timestamp.isoformat(),
                }
                for evt in tool_completed[:last_n]
            ]

        # Node transitions
        edges = bus.get_history(event_type=EventType.EDGE_TRAVERSED, limit=last_n)
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
        """Check on the worker with progressive disclosure.

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
        now = _time.monotonic()
        if focus == "full":
            cooldown = _COOLDOWN_FULL
            tier = "full"
        elif focus is not None:
            cooldown = _COOLDOWN_DETAIL
            tier = "detail"
        else:
            cooldown = 0.0
            tier = "summary"

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
            return "No worker loaded."

        reg = runtime.get_graph_registration(runtime.graph_id)
        if reg is None:
            return "No worker loaded."

        # --- Build preamble (always cheap) ---
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
            "Check on the worker. Returns a brief prose summary by default. "
            "Use 'focus' to drill into specifics:\n"
            "- activity: current node, transitions, latest LLM output\n"
            "- memory: worker's accumulated knowledge and state\n"
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

    # --- inject_worker_message ------------------------------------------------

    async def inject_worker_message(content: str) -> str:
        """Send a message to the running worker agent.

        Injects the message into the worker's active node conversation.
        Use this to relay user instructions to the worker.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        graph_id = runtime.graph_id
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": "Worker graph not found"})

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
                "error": "No active worker node found — worker may be idle.",
            }
        )

    _inject_tool = Tool(
        name="inject_worker_message",
        description=(
            "Send a message to the running worker agent. The message is injected "
            "into the worker's active node conversation. Use this to relay user "
            "instructions or concerns. The worker must be running."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Message content to send to the worker",
                },
            },
            "required": ["content"],
        },
    )
    registry.register(
        "inject_worker_message", _inject_tool, lambda inputs: inject_worker_message(**inputs)
    )
    tools_registered += 1

    # --- list_credentials -----------------------------------------------------

    async def list_credentials(credential_id: str = "") -> str:
        """List all authorized credentials (Aden OAuth + local encrypted store).

        Returns credential IDs, aliases, status, and identity metadata.
        Never returns secret values. Optionally filter by credential_id.
        """
        try:
            # Primary: CredentialStoreAdapter sees both Aden OAuth and local accounts
            from aden_tools.credentials import CredentialStoreAdapter

            store = CredentialStoreAdapter.default()
            all_accounts = store.get_all_account_info()

            # Filter by credential_id / provider if requested
            if credential_id:
                all_accounts = [
                    a
                    for a in all_accounts
                    if a.get("credential_id", "").startswith(credential_id)
                    or a.get("provider", "") == credential_id
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
            from framework.credentials.local.registry import LocalCredentialRegistry

            registry = LocalCredentialRegistry.default()
            accounts = registry.list_accounts(
                credential_id=credential_id or None,
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
                    await session_manager.unload_worker(manager_session_id)
                except Exception as e:
                    logger.error("Failed to unload existing worker: %s", e, exc_info=True)
                    return json.dumps({"error": f"Failed to unload existing worker: {e}"})

            try:
                resolved_path = validate_agent_path(agent_path)
            except ValueError as e:
                return json.dumps({"error": str(e)})
            if not resolved_path.exists():
                return json.dumps({"error": f"Agent path does not exist: {agent_path}"})

            # Pre-check: verify the module exports goal/nodes/edges before
            # attempting the full load.  This gives the queen an actionable
            # error message instead of a cryptic ImportError or TypeError.
            try:
                import importlib
                import sys as _sys

                pkg_name = resolved_path.name
                parent_dir = str(resolved_path.resolve().parent)
                # Temporarily put parent on sys.path for import
                if parent_dir not in _sys.path:
                    _sys.path.insert(0, parent_dir)
                # Evict stale cached modules
                stale = [n for n in _sys.modules if n == pkg_name or n.startswith(f"{pkg_name}.")]
                for n in stale:
                    del _sys.modules[n]

                mod = importlib.import_module(pkg_name)
                missing_attrs = [
                    attr for attr in ("goal", "nodes", "edges") if getattr(mod, attr, None) is None
                ]
                if missing_attrs:
                    return json.dumps(
                        {
                            "error": (
                                f"Agent module '{pkg_name}' is missing module-level "
                                f"attributes: {', '.join(missing_attrs)}. "
                                f"Fix: in {pkg_name}/__init__.py, add "
                                f"'from .agent import {', '.join(missing_attrs)}' "
                                f"so that 'import {pkg_name}' exposes them at package level."
                            )
                        }
                    )
            except Exception as pre_err:
                return json.dumps(
                    {
                        "error": (
                            f"Failed to import agent module '{resolved_path.name}': {pre_err}. "
                            f"Fix: ensure {resolved_path.name}/__init__.py exists and can be "
                            f"imported without errors (check syntax, missing dependencies, "
                            f"and relative imports)."
                        )
                    }
                )

            try:
                updated_session = await session_manager.load_worker(
                    manager_session_id,
                    str(resolved_path),
                )
                info = updated_session.worker_info

                # Validate that all tools declared by nodes are registered
                loaded_runtime = _get_runtime()
                if loaded_runtime is not None:
                    available_tool_names = {t.name for t in loaded_runtime._tools}
                    missing_by_node: dict[str, list[str]] = {}
                    for node in loaded_runtime.graph.nodes:
                        if node.tools:
                            missing = set(node.tools) - available_tool_names
                            if missing:
                                missing_by_node[f"{node.name} (id={node.id})"] = sorted(missing)
                    if missing_by_node:
                        # Unload the broken worker
                        try:
                            await session_manager.unload_worker(manager_session_id)
                        except Exception:
                            pass
                        details = "; ".join(
                            f"Node '{k}' missing {v}" for k, v in missing_by_node.items()
                        )
                        return json.dumps(
                            {
                                "error": (
                                    f"Tool validation failed: {details}. "
                                    "Fix node tool declarations or add the missing "
                                    "tools, then try loading again."
                                )
                            }
                        )

                # Switch to staging phase after successful load + validation
                if phase_state is not None:
                    await phase_state.switch_to_staging()

                worker_name = info.name if info else updated_session.worker_id
                return json.dumps(
                    {
                        "status": "loaded",
                        "phase": "staging",
                        "message": (
                            f"Successfully loaded '{worker_name}'. "
                            "You are now in STAGING phase. "
                            "Call run_agent_with_input(task) to start the worker, "
                            "or stop_worker_and_edit() to go back to building."
                        ),
                        "worker_id": updated_session.worker_id,
                        "worker_name": worker_name,
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
                "path (e.g. 'exports/my_agent') to make it available immediately. "
                "The user will see the agent's graph and can interact with it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_path": {
                        "type": "string",
                        "description": ("Path to the agent directory (e.g. 'exports/my_agent')"),
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

        Performs preflight checks (credentials, MCP resync), triggers the
        worker's default entry point, and switches to running phase.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        try:
            # Pre-flight: validate credentials and resync MCP servers.
            loop = asyncio.get_running_loop()

            async def _preflight():
                cred_error: CredentialError | None = None
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: validate_credentials(
                            runtime.graph.nodes,
                            interactive=False,
                            skip=False,
                        ),
                    )
                except CredentialError as e:
                    cred_error = e

                runner = getattr(session, "runner", None)
                if runner:
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda: runner._tool_registry.resync_mcp_servers_if_needed(),
                        )
                    except Exception as e:
                        logger.warning("MCP resync failed: %s", e)

                if cred_error is not None:
                    raise cred_error

            try:
                await asyncio.wait_for(_preflight(), timeout=_START_PREFLIGHT_TIMEOUT)
            except TimeoutError:
                logger.warning(
                    "run_agent_with_input preflight timed out after %ds — proceeding",
                    _START_PREFLIGHT_TIMEOUT,
                )
            except CredentialError:
                raise  # handled below

            # Resume timers in case they were paused by a previous stop
            runtime.resume_timers()

            # Get session state from any prior execution for memory continuity
            session_state = runtime._get_primary_session_state("default") or {}

            if session_id:
                session_state["resume_session_id"] = session_id

            exec_id = await runtime.trigger(
                entry_point_id="default",
                input_data={"user_request": task},
                session_state=session_state,
            )

            # Switch to running phase
            if phase_state is not None:
                await phase_state.switch_to_running()

            return json.dumps(
                {
                    "status": "started",
                    "phase": "running",
                    "execution_id": exec_id,
                    "task": task,
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
            return json.dumps({"error": f"Failed to start worker: {e}"})

    _run_input_tool = Tool(
        name="run_agent_with_input",
        description=(
            "Run the loaded worker agent with the given task. Validates credentials, "
            "triggers the worker's default entry point, and switches to running phase. "
            "Use this after loading an agent (staging phase) to start execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or input for the worker agent to execute",
                },
            },
            "required": ["task"],
        },
    )
    registry.register(
        "run_agent_with_input", _run_input_tool, lambda inputs: run_agent_with_input(**inputs)
    )
    tools_registered += 1

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
