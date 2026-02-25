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

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def build_worker_profile(runtime: AgentRuntime) -> str:
    """Build a worker capability profile from its graph/goal definition.

    Injected into the queen's system prompt so it knows what the worker
    can and cannot do — enabling correct delegation decisions.
    """
    graph = runtime.graph
    goal = runtime.goal

    lines = ["\n\n# Worker Profile"]
    lines.append(f"Agent: {runtime.graph_id}")
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

    async def start_worker(task: str) -> str:
        """Start the worker agent with a task description.

        Triggers the worker's default entry point with the given task.
        Returns immediately — the worker runs asynchronously.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        try:
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
        """Cancel all active worker executions.

        Stops the worker gracefully. Returns the IDs of cancelled executions.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No worker loaded in this session."})

        cancelled = []
        graph_id = runtime.graph_id

        # Get the primary graph's streams
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": "Worker graph not found"})

        for _ep_id, stream in reg.streams.items():
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

    # --- get_worker_status ----------------------------------------------------

    async def get_worker_status() -> str:
        """Check if the worker is idle, running, or waiting for user input.

        Returns worker identity, execution state, active node, and iteration count.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"status": "not_loaded", "message": "No worker loaded."})

        graph_id = runtime.graph_id
        goal = runtime.goal
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"status": "not_loaded"})

        base = {
            "worker_graph_id": graph_id,
            "worker_goal": getattr(goal, "name", graph_id),
        }

        active_execs = []
        for ep_id, stream in reg.streams.items():
            for exec_id in stream.active_execution_ids:
                active_execs.append(
                    {
                        "execution_id": exec_id,
                        "entry_point": ep_id,
                    }
                )

        if not active_execs:
            return json.dumps(
                {
                    **base,
                    "status": "idle",
                    "message": "Worker has no active executions.",
                }
            )

        # Check if the worker is waiting for user input
        waiting_nodes = []
        for _ep_id, stream in reg.streams.items():
            waiting_nodes.extend(stream.get_waiting_nodes())

        status = "waiting_for_input" if waiting_nodes else "running"
        result = {
            **base,
            "status": status,
            "active_executions": active_execs,
        }
        if waiting_nodes:
            result["waiting_node_id"] = waiting_nodes[0]["node_id"]
        return json.dumps(result)

    _status_tool = Tool(
        name="get_worker_status",
        description=(
            "Check the worker agent's current state: idle (no execution), "
            "running (actively processing), or waiting_for_input (blocked on "
            "user response). Returns execution details."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("get_worker_status", _status_tool, lambda inputs: get_worker_status())
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
                return json.dumps(
                    {
                        "error": "A worker is already loaded in this session. "
                        "Unload it first or open a new tab."
                    }
                )

            resolved_path = Path(agent_path).resolve()
            if not resolved_path.exists():
                return json.dumps({"error": f"Agent path does not exist: {resolved_path}"})

            try:
                updated_session = await session_manager.load_worker(
                    manager_session_id,
                    str(resolved_path),
                )
                info = updated_session.worker_info
                return json.dumps(
                    {
                        "status": "loaded",
                        "worker_id": updated_session.worker_id,
                        "worker_name": info.name if info else updated_session.worker_id,
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

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
