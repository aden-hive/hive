"""Queen lifecycle tools for worker management.

These tools give the Queen agent control over the worker agent's lifecycle.
They close over a reference to the worker's ``AgentRuntime`` and the shared
``EventBus``, following the same pattern as ``session_graph_tools.py``.

Usage::

    from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

    register_queen_lifecycle_tools(
        registry=queen_tool_registry,
        worker_runtime=worker_runtime,
        event_bus=event_bus,
        storage_path=storage_path,
    )
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import AgentRuntime
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


def register_queen_lifecycle_tools(
    registry: ToolRegistry,
    worker_runtime: AgentRuntime,
    event_bus: EventBus,
    storage_path: Path | None = None,
) -> int:
    """Register queen lifecycle tools bound to *worker_runtime*.

    Returns the number of tools registered.
    """
    from framework.llm.provider import Tool

    tools_registered = 0

    # --- start_worker ---------------------------------------------------------

    async def start_worker(task: str) -> str:
        """Start the worker agent with a task description.

        Triggers the worker's default entry point with the given task.
        Returns immediately — the worker runs asynchronously.
        """
        try:
            # Get session state from any prior execution for memory continuity
            session_state = worker_runtime._get_primary_session_state("default")

            exec_id = await worker_runtime.trigger(
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
        cancelled = []
        graph_id = worker_runtime.graph_id

        # Get the primary graph's streams
        reg = worker_runtime.get_graph_registration(graph_id)
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

        return json.dumps(
            {
                "status": "stopped" if cancelled else "no_active_executions",
                "cancelled": cancelled,
            }
        )

    _stop_tool = Tool(
        name="stop_worker",
        description=(
            "Cancel the worker agent's active execution. "
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
        graph_id = worker_runtime.graph_id
        goal = worker_runtime.goal
        reg = worker_runtime.get_graph_registration(graph_id)
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
        graph_id = worker_runtime.graph_id
        reg = worker_runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": "Worker graph not found"})

        # Find an active node that can accept injected input
        for stream in reg.streams.values():
            injectable = stream.get_injectable_nodes()
            if injectable:
                target_node_id = injectable[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content)
                if ok:
                    return json.dumps({
                        "status": "delivered",
                        "node_id": target_node_id,
                        "content_preview": content[:100],
                    })

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

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
