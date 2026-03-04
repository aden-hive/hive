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
class QueenModeState:
    """Mutable state container for queen operating mode.

    Three modes: building → staging → running.
    Shared between the dynamic_tools_provider callback and tool handlers
    that trigger mode transitions.
    """

    mode: str = "building"  # "building", "staging", or "running"
    building_tools: list = field(default_factory=list)  # list[Tool]
    staging_tools: list = field(default_factory=list)  # list[Tool]
    running_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_MODE_CHANGED events

    def get_current_tools(self) -> list:
        """Return tools for the current mode."""
        if self.mode == "running":
            return list(self.running_tools)
        if self.mode == "staging":
            return list(self.staging_tools)
        return list(self.building_tools)

    async def _emit_mode_event(self) -> None:
        """Publish a QUEEN_MODE_CHANGED event so the frontend updates the tag."""
        if self.event_bus is not None:
            await self.event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_MODE_CHANGED,
                    stream_id="queen",
                    data={"mode": self.mode},
                )
            )

    async def switch_to_running(self, source: str = "tool") -> None:
        """Switch to running mode and notify the queen.

        Args:
            source: Who triggered the switch — "tool" (queen LLM),
                "frontend" (user clicked Run), or "auto" (system).
        """
        if self.mode == "running":
            return
        self.mode = "running"
        tool_names = [t.name for t in self.running_tools]
        logger.info("Queen mode → running (source=%s, tools: %s)", source, tool_names)
        await self._emit_mode_event()
        if self.inject_notification:
            if source == "frontend":
                msg = (
                    "[MODE CHANGE] The user clicked Run in the UI. Switched to RUNNING mode. "
                    "Worker is now executing. You have monitoring/lifecycle tools: "
                    + ", ".join(tool_names) + "."
                )
            else:
                msg = (
                    "[MODE CHANGE] Switched to RUNNING mode. "
                    "Worker is executing. You now have monitoring/lifecycle tools: "
                    + ", ".join(tool_names) + "."
                )
            await self.inject_notification(msg)

    async def switch_to_staging(self, source: str = "tool") -> None:
        """Switch to staging mode and notify the queen.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.mode == "staging":
            return
        self.mode = "staging"
        tool_names = [t.name for t in self.staging_tools]
        logger.info("Queen mode → staging (source=%s, tools: %s)", source, tool_names)
        await self._emit_mode_event()
        if self.inject_notification:
            if source == "frontend":
                msg = (
                    "[MODE CHANGE] The user stopped the worker from the UI. Switched to STAGING mode. "
                    "Agent is still loaded. Available tools: " + ", ".join(tool_names) + "."
                )
            elif source == "auto":
                msg = (
                    "[MODE CHANGE] Worker execution completed. Switched to STAGING mode. "
                    "Agent is still loaded. Call run_agent_with_input(task) to run again. "
                    "Available tools: " + ", ".join(tool_names) + "."
                )
            else:
                msg = (
                    "[MODE CHANGE] Switched to STAGING mode. "
                    "Agent loaded and ready. Call run_agent_with_input(task) to start, "
                    "or stop_worker_and_edit() to go back to building. "
                    "Available tools: " + ", ".join(tool_names) + "."
                )
            await self.inject_notification(msg)

    async def switch_to_building(self, source: str = "tool") -> None:
        """Switch to building mode and notify the queen.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.mode == "building":
            return
        self.mode = "building"
        tool_names = [t.name for t in self.building_tools]
        logger.info("Queen mode → building (source=%s, tools: %s)", source, tool_names)
        await self._emit_mode_event()
        if self.inject_notification:
            await self.inject_notification(
                "[MODE CHANGE] Switched to BUILDING mode. "
                "Lifecycle tools removed. Full coding tools restored. "
                "Call load_built_agent(path) when ready to stage."
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
    mode_state: QueenModeState | None = None,
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
        mode_state: (Optional) Mutable mode state for building/running
            mode switching. When provided, load_built_agent switches to
            running mode and stop_worker_and_edit switches to building mode.

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

    async def stop_worker() -> str:
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
                        ok = await stream.cancel_execution(exec_id)
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
        """Stop the worker and switch to building mode for editing the agent."""
        stop_result = await stop_worker()

        # Switch to building mode
        if mode_state is not None:
            await mode_state.switch_to_building()

        result = json.loads(stop_result)
        result["mode"] = "building"
        result["message"] = (
            "Worker stopped. You are now in building mode. "
            "Use your coding tools to modify the agent, then call "
            "load_built_agent(path) to stage it again."
        )
        return json.dumps(result)

    _stop_edit_tool = Tool(
        name="stop_worker_and_edit",
        description=(
            "Stop the running worker and switch to building mode. "
            "Use this when you need to modify the agent's code, nodes, or configuration. "
            "After editing, call load_built_agent(path) to reload and run."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "stop_worker_and_edit", _stop_edit_tool, lambda inputs: stop_worker_and_edit()
    )
    tools_registered += 1

    # --- stop_worker (Running → Staging) -------------------------------------

    async def stop_worker_to_staging() -> str:
        """Stop the running worker and switch to staging mode.

        After stopping, ask the user whether they want to:
        1. Re-run the agent with new input → call run_agent_with_input(task)
        2. Edit the agent code → call stop_worker_and_edit() to go to building mode
        """
        stop_result = await stop_worker()

        # Switch to staging mode
        if mode_state is not None:
            await mode_state.switch_to_staging()

        result = json.loads(stop_result)
        result["mode"] = "staging"
        result["message"] = (
            "Worker stopped. You are now in staging mode. "
            "Ask the user: would they like to re-run with new input, "
            "or edit the agent code?"
        )
        return json.dumps(result)

    _stop_worker_tool = Tool(
        name="stop_worker",
        description=(
            "Stop the running worker and switch to staging mode. "
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

    _status_last_called: dict[str, float] = {}  # {"ts": monotonic time}
    _STATUS_COOLDOWN = 30.0  # seconds between full status checks

    async def get_worker_status(last_n: int = 20) -> str:
        """Comprehensive worker status: state, execution details, and recent activity.

        Returns everything the queen needs in a single call:
        - Identity and high-level state (idle / running / waiting_for_input)
        - Active execution details (elapsed time, current node, iteration)
        - Running tool calls (started but not yet completed)
        - Recent completed tool calls (name, success/error)
        - Node transitions (execution path)
        - Retries, stalls, and constraint violations
        - Goal progress and token consumption

        Args:
            last_n: Number of recent events to include per category (default 20).
        """
        import time as _time

        now = _time.monotonic()
        last = _status_last_called.get("ts", 0.0)
        if now - last < _STATUS_COOLDOWN:
            remaining = int(_STATUS_COOLDOWN - (now - last))
            return json.dumps(
                {
                    "status": "cooldown",
                    "message": (
                        f"Status was checked {int(now - last)}s ago. "
                        f"Wait {remaining}s before checking again. "
                        "Do NOT call this tool in a loop — wait for user input instead."
                    ),
                }
            )
        _status_last_called["ts"] = now

        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"status": "not_loaded", "message": "No worker loaded."})

        graph_id = runtime.graph_id
        goal = runtime.goal
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"status": "not_loaded"})

        result: dict[str, Any] = {
            "worker_graph_id": graph_id,
            "worker_goal": getattr(goal, "name", graph_id),
        }

        # --- Execution state ---
        active_execs = []
        for ep_id, stream in reg.streams.items():
            for exec_id in stream.active_execution_ids:
                exec_info: dict[str, Any] = {
                    "execution_id": exec_id,
                    "entry_point": ep_id,
                }
                ctx = stream.get_context(exec_id)
                if ctx:
                    from datetime import datetime

                    elapsed = (datetime.now() - ctx.started_at).total_seconds()
                    exec_info["elapsed_seconds"] = round(elapsed, 1)
                    exec_info["exec_status"] = ctx.status
                active_execs.append(exec_info)

        if not active_execs:
            result["status"] = "idle"
            result["message"] = "Worker has no active executions."
        else:
            waiting_nodes = []
            for _ep_id, stream in reg.streams.items():
                waiting_nodes.extend(stream.get_waiting_nodes())

            result["status"] = "waiting_for_input" if waiting_nodes else "running"
            result["active_executions"] = active_execs
            if waiting_nodes:
                result["waiting_node_id"] = waiting_nodes[0]["node_id"]

        result["agent_idle_seconds"] = round(runtime.agent_idle_seconds, 1)

        # --- EventBus enrichment ---
        bus = _get_event_bus()
        if not bus:
            return json.dumps(result)

        try:
            # Pending user question (from ask_user tool)
            if result.get("status") == "waiting_for_input":
                input_events = bus.get_history(event_type=EventType.CLIENT_INPUT_REQUESTED, limit=1)
                if input_events:
                    prompt = input_events[0].data.get("prompt", "")
                    if prompt:
                        result["pending_question"] = prompt
            # Current node
            edge_events = bus.get_history(event_type=EventType.EDGE_TRAVERSED, limit=1)
            if edge_events:
                target = edge_events[0].data.get("target_node")
                if target:
                    result["current_node"] = target

            # Current iteration
            iter_events = bus.get_history(event_type=EventType.NODE_LOOP_ITERATION, limit=1)
            if iter_events:
                result["current_iteration"] = iter_events[0].data.get("iteration")

            # Running tool calls (started but not yet completed)
            tool_started = bus.get_history(event_type=EventType.TOOL_CALL_STARTED, limit=last_n * 2)
            tool_completed = bus.get_history(
                event_type=EventType.TOOL_CALL_COMPLETED, limit=last_n * 2
            )
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

            # Recent completed tool calls
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

            # Goal progress
            try:
                progress = await runtime.get_goal_progress()
                if progress:
                    result["goal_progress"] = progress
            except Exception:
                pass

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

            # Execution completions/failures
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
        except Exception:
            pass  # Non-critical enrichment

        return json.dumps(result, default=str, ensure_ascii=False)

    _status_tool = Tool(
        name="get_worker_status",
        description=(
            "Get comprehensive worker status: state (idle/running/waiting_for_input), "
            "execution details (elapsed time, current node, iteration), "
            "recent tool calls, running tools, node transitions, retries, "
            "stalls, constraint violations, goal progress, and token consumption. "
            "One call gives the queen a complete picture."
        ),
        parameters={
            "type": "object",
            "properties": {
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent events per category (default 20)",
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
        Use this to relay user instructions or concerns to the worker.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        graph_id = runtime.graph_id
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": "Worker graph not found"})

        # Find an active node that can accept injected input
        for stream in reg.streams.values():
            injectable = stream.get_injectable_nodes()
            if injectable:
                target_node_id = injectable[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content)
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

            try:
                updated_session = await session_manager.load_worker(
                    manager_session_id,
                    str(resolved_path),
                )
                info = updated_session.worker_info

                # Switch to staging mode after successful load
                if mode_state is not None:
                    await mode_state.switch_to_staging()

                worker_name = info.name if info else updated_session.worker_id
                return json.dumps(
                    {
                        "status": "loaded",
                        "mode": "staging",
                        "message": (
                            f"Successfully loaded '{worker_name}'. "
                            "You are now in STAGING mode. "
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
        worker's default entry point, and switches to running mode.
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

            # Switch to running mode
            if mode_state is not None:
                await mode_state.switch_to_running()

            return json.dumps(
                {
                    "status": "started",
                    "mode": "running",
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
            "triggers the worker's default entry point, and switches to running mode. "
            "Use this after loading an agent (staging mode) to start execution."
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
