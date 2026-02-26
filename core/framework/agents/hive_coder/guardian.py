"""Attach the Hive Coder's guardian node to any agent runtime.

Usage::

    from framework.agents.hive_coder.guardian import attach_guardian

    runner._setup()
    attach_guardian(runner._agent_runtime, runner._tool_registry)
    await runner._agent_runtime.start()

Must be called **before** ``runtime.start()`` — it injects the
guardian node into the graph and registers an event-driven entry point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import AgentRuntime

from framework.runtime.execution_stream import EntryPointSpec

from .nodes import ALL_GUARDIAN_TOOLS, guardian_node

logger = logging.getLogger(__name__)

GUARDIAN_ENTRY_POINT = EntryPointSpec(
    id="guardian",
    name="Agent Guardian",
    entry_node="guardian",
    trigger_type="event",
    trigger_config={
        "event_types": [
            "execution_failed",
            "node_stalled",
            "node_tool_doom_loop",
            "constraint_violation",
        ],
        "exclude_own_graph": False,
    },
    isolation_level="shared",
)


def attach_guardian(
    runtime: AgentRuntime,
    tool_registry: ToolRegistry,
) -> None:
    """Inject hive_coder's guardian node into *runtime*'s graph.

    1. Registers graph lifecycle tools if not already present.
    2. Refreshes the runtime's tool list and executor.
    3. Adds the guardian node (with dynamically filtered tools) to the graph.
    4. Registers an event-driven entry point that fires on execution failures,
       stalls, tool doom loops, and constraint violations.

    Must be called **before** ``runtime.start()``.

    Raises:
        RuntimeError: If the runtime is already running.
    """
    from framework.tools.session_graph_tools import register_graph_tools

    # 1. Register graph lifecycle tools if not already present
    if not tool_registry.has_tool("load_agent"):
        register_graph_tools(tool_registry, runtime)

    # 2. Refresh tool schemas and executor on the runtime
    runtime._tools = list(tool_registry.get_tools().values())
    runtime._tool_executor = tool_registry.get_executor()

    # 3. Filter guardian tools to only those available in the registry
    available = set(tool_registry.get_tools().keys())
    filtered_tools = [t for t in ALL_GUARDIAN_TOOLS if t in available]

    # Build guardian node with filtered tool list
    node = guardian_node.model_copy(update={"tools": filtered_tools})

    # Add to the runtime's graph (so register_entry_point validation passes)
    runtime.graph.nodes.append(node)

    # Mark guardian as reachable in graph-level entry_points so
    # GraphSpec.validate() doesn't flag it as unreachable.
    runtime.graph.entry_points["guardian"] = "guardian"

    # 4. Register event-driven entry point
    runtime.register_entry_point(GUARDIAN_ENTRY_POINT)

    logger.info(
        "Guardian attached with %d tools: %s",
        len(filtered_tools),
        filtered_tools,
    )
