"""Tests for economic mode budget propagation through AgentRunner.__init__."""

from pathlib import Path
from unittest.mock import patch

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec
from framework.runner.runner import AgentRunner


def _make_graph(loop_config: dict | None = None) -> GraphSpec:
    node_spec = NodeSpec(
        id="main",
        name="Main",
        description="",
        node_type="event_loop",
        output_keys=[],
    )
    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        entry_node="main",
        terminal_nodes=["main"],
        nodes=[node_spec],
        edges=[],
        loop_config=loop_config or {},
    )


def _make_runner(node_budget: int | None, graph: GraphSpec | None = None) -> AgentRunner:
    """Build a minimal AgentRunner, bypassing preload validation."""
    if graph is None:
        graph = _make_graph()
    goal = Goal(id="test-goal", name="Test Goal", description="")
    with patch("framework.runner.runner.run_preload_validation"):
        return AgentRunner(
            agent_path=Path("/tmp/fake-agent"),
            graph=graph,
            goal=goal,
            skip_credential_validation=True,
            node_budget=node_budget,
        )


class TestAgentRunnerBudgetPropagation:
    """Verify that AgentRunner propagates node_budget into graph.loop_config."""

    def test_budget_is_set_in_loop_config(self):
        runner = _make_runner(node_budget=7)
        assert runner.graph.loop_config["max_paid_calls_per_node"] == 7

    def test_zero_budget_is_set_in_loop_config(self):
        """node_budget=0 is valid (block all paid calls) and must not be silently ignored."""
        runner = _make_runner(node_budget=0)
        assert runner.graph.loop_config["max_paid_calls_per_node"] == 0

    def test_none_budget_does_not_set_loop_config(self):
        """When node_budget is None, loop_config should not contain the key."""
        runner = _make_runner(node_budget=None)
        assert "max_paid_calls_per_node" not in runner.graph.loop_config

    def test_existing_loop_config_is_preserved(self):
        """Setting node_budget should not wipe other loop_config entries."""
        graph = _make_graph(loop_config={"max_iterations": 42})
        runner = _make_runner(node_budget=3, graph=graph)
        assert runner.graph.loop_config["max_paid_calls_per_node"] == 3
        assert runner.graph.loop_config["max_iterations"] == 42
