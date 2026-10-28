"""Regression tests for parallel fan-out error handling.

Covers https://github.com/aden-hive/hive/issues/2310:
a parallel branch whose target node is missing from the graph must
surface a clear RuntimeError, not an AttributeError from the
error-reporting path.
"""

from __future__ import annotations

import pytest

from framework.orchestrator.edge import EdgeSpec, GraphSpec
from framework.orchestrator.goal import Goal
from framework.orchestrator.node import DataBuffer, NodeResult, NodeSpec
from framework.orchestrator.orchestrator import (
    Orchestrator,
    ParallelExecutionConfig,
)
from framework.tracker.decision_tracker import DecisionTracker


@pytest.mark.asyncio
async def test_parallel_branch_missing_node_raises_runtime_error_not_attribute_error(
    tmp_path,
) -> None:
    """Missing branch target should raise RuntimeError with the node ID, not AttributeError."""
    runtime = DecisionTracker(storage_path=tmp_path / "runtime")
    executor = Orchestrator(
        runtime=runtime,
        parallel_config=ParallelExecutionConfig(on_branch_failure="fail_all"),
    )

    source_spec = NodeSpec(
        id="source",
        name="Source Node",
        description="Fan-out source node",
        node_type="event_loop",
    )
    graph = GraphSpec(
        id="fanout-graph",
        goal_id="fanout-goal",
        entry_node="source",
        nodes=[source_spec],
        edges=[
            EdgeSpec(
                id="edge-to-missing",
                source="source",
                target="missing_node",
            ),
        ],
    )
    goal = Goal(
        id="fanout-goal",
        name="Fanout",
        description="Fan-out with a missing branch target",
    )

    with pytest.raises(RuntimeError) as excinfo:
        await executor._execute_parallel_branches(
            graph=graph,
            goal=goal,
            edges=graph.edges,
            buffer=DataBuffer(),
            source_result=NodeResult(success=True, output={}),
            source_node_spec=source_spec,
            path=[],
        )

    # The error message must reference the missing branch by node ID
    # and must not leak the original AttributeError.
    assert "missing_node" in str(excinfo.value)
    assert "AttributeError" not in str(excinfo.value)
