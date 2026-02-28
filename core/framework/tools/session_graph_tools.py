"""Graph lifecycle tools for multi-graph sessions.

These tools allow an agent (e.g. hive_coder) to load, unload, start,
restart, and query other agent graphs within the same runtime session.

Usage::

    from framework.tools.session_graph_tools import register_graph_tools

    register_graph_tools(tool_registry, runtime)

The tools are registered as async Python functions on the ToolRegistry.
They close over the ``AgentRuntime`` instance — no ContextVar needed
since the runtime is a stable, long-lived object.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import AgentRuntime

logger = logging.getLogger(__name__)


def register_graph_tools(registry: ToolRegistry, runtime: AgentRuntime) -> int:
    """Register graph lifecycle tools bound to *runtime*.

    Returns the number of tools registered.
    """
    from framework.llm.provider import Tool

    tools_registered = 0

    # --- load_agent -----------------------------------------------------------

    async def load_agent(agent_path: str) -> str:
        """Load an agent graph from disk into the running session.

        The agent is imported from *agent_path* (a directory containing
        ``agent.py``).  Its graph, goal, and entry points are registered
        as a secondary graph on the runtime.  Returns a JSON summary.
        """
        from framework.runner.runner import AgentRunner
        from framework.runtime.execution_stream import EntryPointSpec

        path = Path(agent_path).resolve()
        if not path.exists():
            return json.dumps({"error": f"Agent path does not exist: {path}"})

        try:
            runner = AgentRunner.load(path)
        except Exception as exc:
            return json.dumps({"error": f"Failed to load agent: {exc}"})

        graph_id = path.name
        if graph_id in list(runtime.list_graphs()):
            return json.dumps({"error": f"Graph '{graph_id}' is already loaded"})

        # Build entry point dict from the loaded graph
        entry_points: dict[str, EntryPointSpec] = {}

        # Primary entry point
        if runner.graph.entry_node:
            entry_points["default"] = EntryPointSpec(
                id="default",
                name="Default",
                entry_node=runner.graph.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            )

        # Async entry points
        for aep in runner.graph.async_entry_points:
            entry_points[aep.id] = EntryPointSpec(
                id=aep.id,
                name=aep.name,
                entry_node=aep.entry_node,
                trigger_type=aep.trigger_type,
                trigger_config=aep.trigger_config,
                isolation_level=aep.isolation_level,
                priority=aep.priority,
                max_concurrent=aep.max_concurrent,
            )

        await runtime.add_graph(
            graph_id=graph_id,
            graph=runner.graph,
            goal=runner.goal,
            entry_points=entry_points,
        )

        return json.dumps(
            {
                "graph_id": graph_id,
                "entry_points": list(entry_points.keys()),
                "nodes": [n.id for n in runner.graph.nodes],
                "status": "loaded",
            }
        )

    _load_tool = Tool(
        name="load_agent",
        description=(
            "Load an agent graph from disk into the current session. "
            "The agent runs alongside the primary agent, sharing memory and data."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_path": {
                    "type": "string",
                    "description": "Path to the agent directory (containing agent.py)",
                },
            },
            "required": ["agent_path"],
        },
    )
    registry.register("load_agent", _load_tool, lambda inputs: load_agent(**inputs))
    tools_registered += 1

    # --- unload_agent ---------------------------------------------------------

    async def unload_agent(graph_id: str) -> str:
        """Stop and remove a secondary agent graph from the session."""
        try:
            await runtime.remove_graph(graph_id)
            return json.dumps({"graph_id": graph_id, "status": "unloaded"})
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    _unload_tool = Tool(
        name="unload_agent",
        description="Stop and remove a loaded agent graph from the session.",
        parameters={
            "type": "object",
            "properties": {
                "graph_id": {
                    "type": "string",
                    "description": "ID of the graph to unload",
                },
            },
            "required": ["graph_id"],
        },
    )
    registry.register("unload_agent", _unload_tool, lambda inputs: unload_agent(**inputs))
    tools_registered += 1

    # --- start_agent ----------------------------------------------------------

    async def start_agent(
        graph_id: str, entry_point: str = "default", input_data: str = "{}"
    ) -> str:
        """Trigger an entry point on a loaded agent graph."""
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": f"Graph '{graph_id}' not found"})

        stream = reg.streams.get(entry_point)
        if stream is None:
            return json.dumps(
                {
                    "error": f"Entry point '{entry_point}' not found on graph '{graph_id}'",
                    "available": list(reg.streams.keys()),
                }
            )

        try:
            data = json.loads(input_data) if isinstance(input_data, str) else input_data
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON input: {exc}"})

        session_state = runtime._get_primary_session_state(entry_point, source_graph_id=graph_id)
        exec_id = await stream.execute(data, session_state=session_state)
        return json.dumps(
            {
                "graph_id": graph_id,
                "entry_point": entry_point,
                "execution_id": exec_id,
                "status": "triggered",
            }
        )

    _start_tool = Tool(
        name="start_agent",
        description="Trigger an entry point on a loaded agent graph to start execution.",
        parameters={
            "type": "object",
            "properties": {
                "graph_id": {
                    "type": "string",
                    "description": "ID of the graph to start",
                },
                "entry_point": {
                    "type": "string",
                    "description": "Entry point to trigger (default: 'default')",
                },
                "input_data": {
                    "type": "string",
                    "description": "JSON string of input data for the execution",
                },
            },
            "required": ["graph_id"],
        },
    )
    registry.register("start_agent", _start_tool, lambda inputs: start_agent(**inputs))
    tools_registered += 1

    # --- restart_agent --------------------------------------------------------

    async def restart_agent(graph_id: str) -> str:
        """Unload and reload an agent graph (picks up code changes)."""
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            return json.dumps({"error": f"Graph '{graph_id}' not found"})
        if graph_id == runtime.graph_id:
            return json.dumps({"error": "Cannot restart the primary graph"})

        # Remember the graph spec so we can reload it
        # The graph_id is the agent directory name by convention
        # We need to find the original agent path
        # For now, use the graph's id to locate the agent
        try:
            await runtime.remove_graph(graph_id)
        except ValueError as exc:
            return json.dumps({"error": f"Failed to unload: {exc}"})

        # Reload by calling load_agent with the graph_id as path hint
        # The caller should use load_agent explicitly if the path is different
        return json.dumps(
            {
                "graph_id": graph_id,
                "status": "unloaded",
                "note": "Use load_agent to reload with updated code",
            }
        )

    _restart_tool = Tool(
        name="restart_agent",
        description=(
            "Unload an agent graph. Use load_agent afterwards to reload with updated code."
        ),
        parameters={
            "type": "object",
            "properties": {
                "graph_id": {
                    "type": "string",
                    "description": "ID of the graph to restart",
                },
            },
            "required": ["graph_id"],
        },
    )
    registry.register("restart_agent", _restart_tool, lambda inputs: restart_agent(**inputs))
    tools_registered += 1

    # --- list_agents ----------------------------------------------------------

    def list_agents() -> str:
        """List all agent graphs in the current session with their status."""
        graphs = []
        for gid in runtime.list_graphs():
            reg = runtime.get_graph_registration(gid)
            if reg is None:
                continue
            graphs.append(
                {
                    "graph_id": gid,
                    "is_primary": gid == runtime.graph_id,
                    "is_active": gid == runtime.active_graph_id,
                    "entry_points": list(reg.entry_points.keys()),
                    "active_executions": sum(
                        len(s.active_execution_ids) for s in reg.streams.values()
                    ),
                }
            )
        return json.dumps({"graphs": graphs})

    _list_tool = Tool(
        name="list_agents",
        description="List all loaded agent graphs and their status.",
        parameters={"type": "object", "properties": {}},
    )
    registry.register("list_agents", _list_tool, lambda inputs: list_agents())
    tools_registered += 1

    # --- get_user_presence ----------------------------------------------------

    def get_user_presence() -> str:
        """Return user idle time and presence status."""
        idle = runtime.user_idle_seconds
        if idle == float("inf"):
            status = "never_seen"
        elif idle < 120:
            status = "present"
        elif idle < 600:
            status = "idle"
        else:
            status = "away"

        return json.dumps(
            {
                "idle_seconds": idle if idle != float("inf") else None,
                "status": status,
            }
        )

    _presence_tool = Tool(
        name="get_user_presence",
        description=(
            "Check if the user is currently active. Returns idle time "
            "and a status of 'present', 'idle', 'away', or 'never_seen'."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register("get_user_presence", _presence_tool, lambda inputs: get_user_presence())
    tools_registered += 1

    logger.info("Registered %d graph lifecycle tools", tools_registered)
    return tools_registered
