import asyncio
from unittest.mock import MagicMock

import pytest

from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.node import NodeProtocol, NodeSpec
from framework.orchestrator.orchestrator import Orchestrator, ParallelExecutionConfig


class SlowNode(NodeProtocol):
    async def execute(self, state, config, runtime, **kwargs):
        # Hang forever to simulate a stalled node
        await asyncio.sleep(9999)
        return {"result": "done"}


@pytest.mark.asyncio
async def test_orchestrator_sequential_node_timeout():
    # Configure a tiny timeout to fail quickly
    parallel_config = ParallelExecutionConfig()
    parallel_config.node_timeout_seconds = 0.1

    mock_runtime = MagicMock()
    mock_runtime.session_id = "test_session"

    mock_llm = MagicMock()

    orchestrator = Orchestrator(
        runtime=mock_runtime,
        llm=mock_llm,
        parallel_config=parallel_config,
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="wait_goal",
        entry_node="slow_node",
        terminal_nodes=[],
        nodes=[NodeSpec(id="slow_node", name="Slow Node", description="A node that hangs", entry=True, callable=SlowNode)],
        edges=[],
    )

    mock_goal = MagicMock()
    mock_goal.id = "wait_goal"
    mock_goal.description = "Wait"

    result = await orchestrator.execute(
        graph=graph,
        goal=mock_goal,
    )

    # The node should time out, marking the graph execution as failed.
    assert result.success is False
    assert "Execution failed (timed out after 0.1s)" in result.error or "timed out" in str(result.error).lower()
