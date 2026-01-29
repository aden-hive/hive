import pytest
from pathlib import Path

from framework.graph.executor import GraphExecutor
from framework.graph.node import NodeProtocol, NodeContext, NodeResult, NodeSpec
from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.core import Runtime


class StateLeakNode(NodeProtocol):
    def __init__(self):
        self.attempts = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempts += 1

        leaked = ctx.memory.read("dirty_flag")
        if leaked is not None:
            return NodeResult(
                success=False,
                error=f"Dirty state leaked: {leaked}",
            )

        ctx.memory.write("dirty_flag", f"attempt_{self.attempts}")

        if self.attempts == 1:
            return NodeResult(success=False, error="force retry")

        return NodeResult(
            success=True,
            output={"result": "ok", "dirty_flag": f"attempt_{self.attempts}"},
        )


@pytest.mark.asyncio
async def test_retry_state_isolation(tmp_path):
    """
    Regression test for #1274

    Ensures that retries do not observe state mutations
    from previous failed attempts.
    """
    runtime = Runtime(storage_path=tmp_path)
    executor = GraphExecutor(runtime=runtime)

    executor.register_node("test_node", StateLeakNode())

    node = NodeSpec(
        id="test_node",
        name="Test Node",
        description="Retry isolation test",
        node_type="function",
        input_keys=[],
        output_keys=["dirty_flag", "result"],
        max_retries=2,
    )

    graph = GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        entry_node="test_node",
        nodes=[node],
        edges=[],
    )

    goal = Goal(
        id="test",
        name="Retry Isolation",
        description="Verify retry state isolation",
    )

    result = await executor.execute(graph, goal)

    assert result.success is True
    assert result.output["result"] == "ok"
