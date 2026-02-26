"""
Tests for cron timer entry point dependency handling.

Verifies that:
1. croniter is properly declared as an optional dependency
2. Missing croniter produces a clear, actionable error message
3. Invalid cron expressions are caught during validation
"""

import logging
from unittest.mock import patch

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.execution_stream import EntryPointSpec


def _make_simple_graph() -> GraphSpec:
    """Create a minimal graph with a single node for testing."""
    return GraphSpec(
        id="test-graph",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="n1",
                name="entry-node",
                description="Test entry node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
            ),
        ],
        edges=[],
        entry_node="n1",
    )


def _make_goal() -> Goal:
    return Goal(id="g1", name="test", description="test goal")


class TestCronDependencyHandling:
    """Test that cron timer entry points handle missing/invalid croniter gracefully."""

    @pytest.mark.asyncio
    async def test_missing_croniter_logs_actionable_error(self, tmp_path, caplog):
        """When croniter is not installed, the error message should tell the user how to fix it."""
        graph = _make_simple_graph()
        goal = _make_goal()

        runtime = AgentRuntime(
            graph=graph,
            goal=goal,
            storage_path=tmp_path,
        )

        # Register a cron-based entry point
        runtime.register_entry_point(
            EntryPointSpec(
                id="cron-ep",
                name="Cron Entry Point",
                entry_node="n1",
                trigger_type="timer",
                trigger_config={"cron": "*/5 * * * *"},
            )
        )

        # Simulate croniter not being installed
        with (
            patch.dict("sys.modules", {"croniter": None}),
            caplog.at_level(logging.ERROR),
        ):
            await runtime.start()

        # Verify the error message includes installation instructions
        assert any("croniter" in record.message for record in caplog.records), (
            "Expected an error message mentioning 'croniter'"
        )
        assert any("pip install" in record.message for record in caplog.records), (
            "Expected installation instructions in the error message"
        )

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_invalid_cron_expression_logs_warning(self, tmp_path, caplog):
        """Invalid cron expressions should produce a clear warning with the bad expression."""
        graph = _make_simple_graph()
        goal = _make_goal()

        runtime = AgentRuntime(
            graph=graph,
            goal=goal,
            storage_path=tmp_path,
        )

        runtime.register_entry_point(
            EntryPointSpec(
                id="bad-cron-ep",
                name="Bad Cron Entry Point",
                entry_node="n1",
                trigger_type="timer",
                trigger_config={"cron": "not-a-cron-expression"},
            )
        )

        with caplog.at_level(logging.WARNING):
            await runtime.start()

        # Verify we get a warning about the invalid expression
        cron_warnings = [r for r in caplog.records if "bad-cron-ep" in r.message]
        assert len(cron_warnings) > 0, "Expected a warning for the invalid cron expression"

        await runtime.stop()


class TestCronOptionalDependencyDeclared:
    """Verify that croniter is properly declared as an optional dependency."""

    def test_croniter_in_optional_deps(self):
        """The 'cron' optional dependency group should include croniter."""
        import tomllib
        from pathlib import Path

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        optional_deps = config.get("project", {}).get("optional-dependencies", {})
        assert "cron" in optional_deps, (
            "Expected a 'cron' optional dependency group in pyproject.toml"
        )

        cron_deps = optional_deps["cron"]
        assert any("croniter" in dep for dep in cron_deps), (
            "Expected 'croniter' in the 'cron' optional dependency group"
        )
