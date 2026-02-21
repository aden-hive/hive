"""Tests for the FinOps metrics collector."""

from __future__ import annotations

import time

import pytest

from framework.finops.config import FinOpsConfig
from framework.finops.metrics import (
    FinOpsCollector,
    NodeMetrics,
    RunMetrics,
    TokenUsage,
    ToolMetrics,
    get_collector,
    reset_collector,
)


@pytest.fixture(autouse=True)
def reset_global_collector():
    """Reset the global collector before and after each test."""
    reset_collector()
    yield
    reset_collector()


class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_default_values(self):
        """Test default values are zero."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_write_tokens == 0
        assert usage.cache_read_tokens == 0

    def test_total_tokens(self):
        """Test total_tokens property."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_addition(self):
        """Test adding two TokenUsage objects."""
        usage1 = TokenUsage(input_tokens=100, output_tokens=50)
        usage2 = TokenUsage(input_tokens=200, output_tokens=100)
        result = usage1 + usage2
        assert result.input_tokens == 300
        assert result.output_tokens == 150


class TestFinOpsCollector:
    """Tests for FinOpsCollector."""

    def test_initialization(self):
        """Test collector initialization."""
        collector = FinOpsCollector()
        assert collector.config is not None
        assert len(collector._runs) == 0
        assert len(collector._active_runs) == 0

    def test_initialization_with_config(self):
        """Test collector initialization with custom config."""
        config = FinOpsConfig(
            prometheus_enabled=False,
            runaway_failure_threshold=5,
        )
        collector = FinOpsCollector(config)
        assert collector.config.prometheus_enabled is False
        assert collector.config.runaway_failure_threshold == 5

    def test_start_run(self):
        """Test starting a run."""
        collector = FinOpsCollector()
        metrics = collector.start_run(
            run_id="run-1",
            agent_id="agent-1",
            goal_id="goal-1",
            model="claude-3-5-sonnet-20241022",
        )

        assert metrics.run_id == "run-1"
        assert metrics.agent_id == "agent-1"
        assert metrics.goal_id == "goal-1"
        assert metrics.model == "claude-3-5-sonnet-20241022"
        assert metrics.status == "running"
        assert "run-1" in collector._runs
        assert "run-1" in collector._active_runs

    def test_end_run_success(self):
        """Test ending a run successfully."""
        collector = FinOpsCollector()
        collector.start_run("run-1")

        metrics = collector.end_run("run-1", success=True, status="completed")

        assert metrics is not None
        assert metrics.success is True
        assert metrics.status == "completed"
        assert metrics.ended_at is not None
        assert "run-1" not in collector._active_runs
        assert collector._total_runs_success == 1

    def test_end_run_failure(self):
        """Test ending a failed run."""
        collector = FinOpsCollector()
        collector.start_run("run-1")

        metrics = collector.end_run("run-1", success=False, status="failed")

        assert metrics is not None
        assert metrics.success is False
        assert metrics.status == "failed"
        assert collector._total_runs_failed == 1

    def test_end_nonexistent_run(self):
        """Test ending a run that doesn't exist."""
        collector = FinOpsCollector()
        metrics = collector.end_run("nonexistent")
        assert metrics is None

    def test_record_node_start(self):
        """Test recording node start."""
        collector = FinOpsCollector()
        collector.start_run("run-1")

        collector.record_node_start("run-1", "node-1", "event_loop")

        run_metrics = collector.get_run_metrics("run-1")
        assert run_metrics is not None
        assert "node-1" in run_metrics.nodes
        assert run_metrics.nodes["node-1"].execution_count == 1

    def test_record_node_complete(self):
        """Test recording node completion."""
        collector = FinOpsCollector()
        collector.start_run("run-1", model="claude-3-5-sonnet-20241022")
        collector.record_node_start("run-1", "node-1")

        tokens = TokenUsage(input_tokens=100, output_tokens=50)
        collector.record_node_complete(
            run_id="run-1",
            node_id="node-1",
            success=True,
            tokens=tokens,
            latency_ms=100,
            model="claude-3-5-sonnet-20241022",
        )

        run_metrics = collector.get_run_metrics("run-1")
        assert run_metrics is not None
        node = run_metrics.nodes["node-1"]
        assert node.success_count == 1
        assert node.tokens.input_tokens == 100
        assert node.tokens.output_tokens == 50
        assert node.total_latency_ms == 100
        assert node.estimated_cost_usd > 0

    def test_record_node_retry(self):
        """Test recording node retry."""
        collector = FinOpsCollector()
        collector.start_run("run-1")
        collector.record_node_start("run-1", "node-1")

        collector.record_node_retry("run-1", "node-1", error="Timeout")

        run_metrics = collector.get_run_metrics("run-1")
        assert run_metrics.nodes["node-1"].retry_count == 1

    def test_record_tool_call(self):
        """Test recording tool call."""
        collector = FinOpsCollector()
        collector.start_run("run-1")
        collector.record_node_start("run-1", "node-1")

        collector.record_tool_call(
            run_id="run-1",
            node_id="node-1",
            tool_name="web_search",
            latency_ms=50,
            is_error=False,
        )

        run_metrics = collector.get_run_metrics("run-1")
        assert "web_search" in run_metrics.nodes["node-1"].tools
        tool = run_metrics.nodes["node-1"].tools["web_search"]
        assert tool.call_count == 1
        assert tool.error_count == 0

    def test_record_tool_call_error(self):
        """Test recording failed tool call."""
        collector = FinOpsCollector()
        collector.start_run("run-1")
        collector.record_node_start("run-1", "node-1")

        collector.record_tool_call(
            run_id="run-1",
            node_id="node-1",
            tool_name="web_search",
            latency_ms=50,
            is_error=True,
        )

        run_metrics = collector.get_run_metrics("run-1")
        tool = run_metrics.nodes["node-1"].tools["web_search"]
        assert tool.error_count == 1

    def test_record_llm_tokens(self):
        """Test recording LLM token usage."""
        collector = FinOpsCollector()
        collector.start_run("run-1")
        collector.record_node_start("run-1", "node-1")

        cost = collector.record_llm_tokens(
            run_id="run-1",
            node_id="node-1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-3-5-sonnet-20241022",
        )

        assert cost > 0
        run_metrics = collector.get_run_metrics("run-1")
        assert run_metrics.tokens.input_tokens == 1000
        assert run_metrics.tokens.output_tokens == 500

    def test_burn_rate_calculation(self):
        """Test burn rate calculation."""
        collector = FinOpsCollector()
        collector.start_run("run-1")

        collector._record_burn_sample("run-1", 100)
        time.sleep(0.1)
        collector._record_burn_sample("run-1", 200)

        burn_rate = collector.get_burn_rate("run-1", window_seconds=1.0)
        assert burn_rate > 0

    def test_burn_rate_no_samples(self):
        """Test burn rate with no samples."""
        collector = FinOpsCollector()
        burn_rate = collector.get_burn_rate("nonexistent")
        assert burn_rate == 0.0

    def test_runaway_detection_consecutive_failures(self):
        """Test runaway detection via consecutive failures."""
        config = FinOpsConfig(
            runaway_detection_enabled=True,
            runaway_failure_threshold=3,
        )
        collector = FinOpsCollector(config)
        collector.start_run("run-1")

        for _ in range(3):
            collector.record_node_complete(
                run_id="run-1",
                node_id="node-1",
                success=False,
            )

        is_runaway, reason = collector.detect_runaway_loop("run-1")
        assert is_runaway is True
        assert "Consecutive failures" in reason

    def test_runaway_detection_disabled(self):
        """Test runaway detection when disabled."""
        config = FinOpsConfig(runaway_detection_enabled=False)
        collector = FinOpsCollector(config)
        collector.start_run("run-1")

        is_runaway, reason = collector.detect_runaway_loop("run-1")
        assert is_runaway is False
        assert reason == ""

    def test_get_aggregated_metrics(self):
        """Test getting aggregated metrics."""
        collector = FinOpsCollector()

        collector.start_run("run-1", model="claude-3-5-sonnet-20241022")
        collector.record_node_start("run-1", "node-1")
        collector.record_llm_tokens(
            run_id="run-1",
            node_id="node-1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-3-5-sonnet-20241022",
        )
        collector.end_run("run-1", success=True)

        agg = collector.get_aggregated_metrics()

        assert agg["total_runs"] == 1
        assert agg["successful_runs"] == 1
        assert agg["total_input_tokens"] == 1000
        assert agg["total_output_tokens"] == 500
        assert agg["total_estimated_cost_usd"] > 0

    def test_clear_run_metrics(self):
        """Test clearing run metrics."""
        collector = FinOpsCollector()
        collector.start_run("run-1")

        assert collector.get_run_metrics("run-1") is not None

        collector.clear_run_metrics("run-1")

        assert collector.get_run_metrics("run-1") is None

    def test_get_collector_singleton(self):
        """Test that get_collector returns a singleton."""
        collector1 = get_collector()
        collector2 = get_collector()
        assert collector1 is collector2
