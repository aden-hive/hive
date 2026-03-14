"""GCU subagent test: parent event_loop delegates to a GCU subagent.

Tests the subagent delegation pattern where a parent node uses
delegate_to_sub_agent to invoke a GCU (browser) node for a task.
The GCU node has access to browser tools via the GCU MCP server.

Note: This test requires the GCU MCP server (gcu.server) to be available.
If not installed, the test is skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec

from .conftest import make_executor


def _has_gcu_server() -> bool:
    """Check if the GCU MCP server module is available."""
    try:
        import gcu.server  # noqa: F401

        return True
    except ImportError:
        return False


def _build_gcu_subagent_graph() -> GraphSpec:
    """Parent event_loop node with a GCU subagent for browser tasks.

    Structure:
    - parent (event_loop): orchestrator that decides when to delegate
    - browser_worker (gcu): subagent with browser tools
    - parent delegates to browser_worker via delegate_to_sub_agent tool
    - browser_worker is NOT connected by edges (validation rule)
    """
    return GraphSpec(
        id="gcu-subagent-graph",
        goal_id="gcu-test",
        entry_node="parent",
        entry_points={"start": "parent"},
        terminal_nodes=["parent"],
        nodes=[
            NodeSpec(
                id="parent",
                name="Orchestrator",
                description="Orchestrates browser tasks via subagent delegation",
                node_type="event_loop",
                input_keys=["task"],
                output_keys=["result"],
                sub_agents=["browser_worker"],
                system_prompt=(
                    "You are an orchestrator. You have a browser subagent called "
                    "'browser_worker' available via delegate_to_sub_agent.\n\n"
                    "Read the 'task' input and delegate the browser work to "
                    "the browser_worker subagent. When the subagent completes, "
                    "summarize the result and call set_output with key='result'."
                ),
            ),
            NodeSpec(
                id="browser_worker",
                name="Browser Worker",
                description="GCU browser subagent for web tasks",
                node_type="gcu",
                output_keys=["browser_result"],
                system_prompt=(
                    "You are a browser worker subagent. Complete the delegated "
                    "browser task using available browser tools. "
                    "When done, call set_output with key='browser_result' and "
                    "the information you found."
                ),
            ),
        ],
        edges=[],  # GCU subagents must NOT be connected by edges
        memory_keys=["task", "result", "browser_result"],
        conversation_mode="continuous",
    )


def _gcu_goal() -> Goal:
    return Goal(
        id="gcu-test",
        name="GCU Subagent Test",
        description="Test browser subagent delegation",
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_gcu_server(), reason="GCU server not installed")
async def test_gcu_subagent_delegation(runtime, llm_provider, tool_registry, tmp_path):
    """Parent delegates a simple browser task to GCU subagent."""
    # Register GCU MCP server tools
    from framework.graph.gcu import GCU_MCP_SERVER_CONFIG

    repo_root = Path(__file__).resolve().parents[3]
    gcu_config = dict(GCU_MCP_SERVER_CONFIG)
    gcu_config["cwd"] = str(repo_root / "tools")
    tool_registry.register_mcp_server(gcu_config)

    # Expand GCU node tools (mirrors what runner._setup does)
    graph = _build_gcu_subagent_graph()
    gcu_tool_names = tool_registry.get_server_tool_names("gcu-tools")
    if gcu_tool_names:
        for node in graph.nodes:
            if node.node_type == "gcu":
                existing = set(node.tools)
                for tool_name in sorted(gcu_tool_names):
                    if tool_name not in existing:
                        node.tools.append(tool_name)

    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        storage_path=tmp_path / "storage",
    )

    result = await executor.execute(
        graph,
        _gcu_goal(),
        {"task": "Use the browser to navigate to https://example.com and report the page title."},
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_gcu_server(), reason="GCU server not installed")
async def test_gcu_subagent_returns_data(runtime, llm_provider, tool_registry, tmp_path):
    """Verify the parent receives structured data from the GCU subagent."""
    from framework.graph.gcu import GCU_MCP_SERVER_CONFIG

    repo_root = Path(__file__).resolve().parents[3]
    gcu_config = dict(GCU_MCP_SERVER_CONFIG)
    gcu_config["cwd"] = str(repo_root / "tools")
    # Only register if not already registered
    if not tool_registry.get_server_tool_names("gcu-tools"):
        tool_registry.register_mcp_server(gcu_config)

    graph = _build_gcu_subagent_graph()
    gcu_tool_names = tool_registry.get_server_tool_names("gcu-tools")
    if gcu_tool_names:
        for node in graph.nodes:
            if node.node_type == "gcu":
                existing = set(node.tools)
                for tool_name in sorted(gcu_tool_names):
                    if tool_name not in existing:
                        node.tools.append(tool_name)

    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        storage_path=tmp_path / "storage",
    )

    result = await executor.execute(
        graph,
        _gcu_goal(),
        {
            "task": "Use the browser to visit https://example.com and report "
            "what domain the page is on."
        },
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None
    # The result should contain something from the browser
    result_text = str(result.output["result"]).lower()
    assert "example" in result_text
