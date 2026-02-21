"""Core FinOps metrics collector for tracking tokens, costs, and burn rates."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from framework.finops.config import FinOpsConfig
from framework.finops.pricing import estimate_cost

logger = logging.getLogger(__name__)

finops_context: ContextVar[dict[str, Any] | None] = ContextVar("finops_context", default=None)


@dataclass
class TokenUsage:
    """Token usage for a single operation."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass
class ToolMetrics:
    """Metrics for a tool call."""

    tool_name: str
    call_count: int = 0
    error_count: int = 0
    total_latency_ms: int = 0


@dataclass
class NodeMetrics:
    """Metrics for a node execution."""

    node_id: str
    node_type: str = ""
    execution_count: int = 0
    success_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    tokens: TokenUsage = field(default_factory=TokenUsage)
    total_latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    model: str = ""
    tools: dict[str, ToolMetrics] = field(default_factory=dict)


@dataclass
class RunMetrics:
    """Metrics for a complete run."""

    run_id: str
    agent_id: str = ""
    goal_id: str = ""
    status: str = "running"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    total_latency_ms: int = 0
    nodes: dict[str, NodeMetrics] = field(default_factory=dict)
    model: str = ""
    success: bool = False


@dataclass
class BurnRateSample:
    """A sample for burn rate calculation."""

    timestamp: float
    tokens: int


class FinOpsCollector:
    """Central collector for FinOps metrics.

    Collects metrics from:
    - Run lifecycle events
    - Node executions
    - LLM calls
    - Tool invocations

    Provides:
    - Real-time burn rate tracking
    - Cost estimation
    - Runaway loop detection
    - Aggregated metrics for export
    """

    def __init__(self, config: FinOpsConfig | None = None):
        self.config = config or FinOpsConfig.from_env()
        self._runs: dict[str, RunMetrics] = {}
        self._run_samples: dict[str, list[BurnRateSample]] = defaultdict(list)
        self._active_runs: dict[str, float] = {}
        self._consecutive_failures: dict[str, int] = defaultdict(int)
        self._baseline_burn_rate: dict[str, float] = {}
        self._lock = threading.Lock()
        self._total_runs = 0
        self._total_runs_success = 0
        self._total_runs_failed = 0
        self._global_tokens = TokenUsage()
        self._global_cost_usd = 0.0

    def start_run(
        self,
        run_id: str,
        agent_id: str = "",
        goal_id: str = "",
        model: str = "",
    ) -> RunMetrics:
        """Start tracking a new run."""
        with self._lock:
            metrics = RunMetrics(
                run_id=run_id,
                agent_id=agent_id,
                goal_id=goal_id,
                model=model,
                started_at=datetime.now(UTC),
            )
            self._runs[run_id] = metrics
            self._active_runs[run_id] = time.time()
            self._total_runs += 1

            finops_context.set(
                {
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "goal_id": goal_id,
                    "model": model,
                }
            )

            logger.debug(
                f"FinOps: Started run tracking",
                extra={"run_id": run_id, "agent_id": agent_id},
            )
            return metrics

    def end_run(
        self,
        run_id: str,
        success: bool = True,
        status: str = "completed",
    ) -> RunMetrics | None:
        """End tracking for a run."""
        with self._lock:
            metrics = self._runs.get(run_id)
            if not metrics:
                return None

            metrics.ended_at = datetime.now(UTC)
            metrics.success = success
            metrics.status = status

            if run_id in self._active_runs:
                del self._active_runs[run_id]

            if success:
                self._total_runs_success += 1
            else:
                self._total_runs_failed += 1

            self._global_tokens = self._global_tokens + metrics.tokens
            self._global_cost_usd += metrics.estimated_cost_usd

            self._consecutive_failures[run_id] = (
                0 if success else self._consecutive_failures.get(run_id, 0) + 1
            )

            finops_context.set(None)

            logger.debug(
                f"FinOps: Ended run tracking",
                extra={
                    "run_id": run_id,
                    "success": success,
                    "total_tokens": metrics.tokens.total_tokens,
                    "estimated_cost_usd": round(metrics.estimated_cost_usd, 4),
                },
            )
            return metrics

    def record_node_start(
        self,
        run_id: str,
        node_id: str,
        node_type: str = "",
    ) -> None:
        """Record the start of a node execution."""
        with self._lock:
            metrics = self._runs.get(run_id)
            if not metrics:
                return

            if node_id not in metrics.nodes:
                metrics.nodes[node_id] = NodeMetrics(
                    node_id=node_id,
                    node_type=node_type,
                )
            metrics.nodes[node_id].execution_count += 1

    def record_node_complete(
        self,
        run_id: str,
        node_id: str,
        success: bool = True,
        tokens: TokenUsage | None = None,
        latency_ms: int = 0,
        model: str = "",
    ) -> None:
        """Record the completion of a node execution."""
        with self._lock:
            metrics = self._runs.get(run_id)
            if not metrics:
                return

            node_metrics = metrics.nodes.get(node_id)
            if not node_metrics:
                return

            if success:
                node_metrics.success_count += 1
            else:
                node_metrics.error_count += 1

            if tokens:
                node_metrics.tokens = node_metrics.tokens + tokens
                metrics.tokens = metrics.tokens + tokens

                if model:
                    cost = estimate_cost(
                        model,
                        tokens.input_tokens,
                        tokens.output_tokens,
                        tokens.cache_write_tokens,
                        tokens.cache_read_tokens,
                    )
                    node_metrics.estimated_cost_usd += cost
                    metrics.estimated_cost_usd += cost

                    self._record_burn_sample(run_id, tokens.total_tokens)

            node_metrics.total_latency_ms += latency_ms
            metrics.total_latency_ms += latency_ms

            if model:
                node_metrics.model = model
                if not metrics.model:
                    metrics.model = model

    def record_node_retry(
        self,
        run_id: str,
        node_id: str,
        error: str = "",
    ) -> None:
        """Record a node retry event."""
        with self._lock:
            metrics = self._runs.get(run_id)
            if not metrics:
                return

            node_metrics = metrics.nodes.get(node_id)
            if node_metrics:
                node_metrics.retry_count += 1

    def record_tool_call(
        self,
        run_id: str,
        node_id: str,
        tool_name: str,
        latency_ms: int = 0,
        is_error: bool = False,
    ) -> None:
        """Record a tool call event."""
        with self._lock:
            metrics = self._runs.get(run_id)
            if not metrics:
                return

            node_metrics = metrics.nodes.get(node_id)
            if not node_metrics:
                return

            if tool_name not in node_metrics.tools:
                node_metrics.tools[tool_name] = ToolMetrics(tool_name=tool_name)

            tool_metrics = node_metrics.tools[tool_name]
            tool_metrics.call_count += 1
            tool_metrics.total_latency_ms += latency_ms
            if is_error:
                tool_metrics.error_count += 1

    def record_llm_tokens(
        self,
        run_id: str,
        node_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Record LLM token usage and return estimated cost."""
        tokens = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        cost = estimate_cost(
            model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens
        )
        self.record_node_complete(
            run_id=run_id,
            node_id=node_id,
            success=True,
            tokens=tokens,
            model=model,
        )
        return cost

    def _record_burn_sample(self, run_id: str, tokens: int) -> None:
        """Record a sample for burn rate calculation."""
        sample = BurnRate(timestamp=time.time(), tokens=tokens)
        self._run_samples[run_id].append(sample)

        if len(self._run_samples[run_id]) > 100:
            self._run_samples[run_id] = self._run_samples[run_id][-100:]

    def get_burn_rate(self, run_id: str, window_seconds: float = 60.0) -> float:
        """Calculate tokens per minute burn rate for a run."""
        samples = self._run_samples.get(run_id, [])
        if len(samples) < 2:
            return 0.0

        now = time.time()
        window_start = now - window_seconds

        window_samples = [s for s in samples if s.timestamp >= window_start]
        if len(window_samples) < 2:
            return 0.0

        time_span = window_samples[-1].timestamp - window_samples[0].timestamp
        if time_span <= 0:
            return 0.0

        token_diff = sum(s.tokens for s in window_samples)
        tokens_per_second = token_diff / time_span
        return tokens_per_second * 60.0

    def detect_runaway_loop(
        self,
        run_id: str,
        current_failures: int = 0,
    ) -> tuple[bool, str]:
        """Detect if a run is in a runaway loop.

        Returns:
            Tuple of (is_runaway, reason)
        """
        if not self.config.runaway_detection_enabled:
            return False, ""

        consecutive_failures = self._consecutive_failures.get(run_id, 0) + current_failures
        if consecutive_failures >= self.config.runaway_failure_threshold:
            return (
                True,
                f"Consecutive failures ({consecutive_failures}) exceeded threshold ({self.config.runaway_failure_threshold})",
            )

        burn_rate = self.get_burn_rate(run_id)
        if burn_rate > 0:
            baseline = self._baseline_burn_rate.get(run_id)
            if baseline is None:
                self._baseline_burn_rate[run_id] = burn_rate
            elif burn_rate > baseline * self.config.runaway_burn_rate_multiplier:
                return (
                    True,
                    f"Burn rate ({burn_rate:.1f} tokens/min) is {self.config.runaway_burn_rate_multiplier}x baseline ({baseline:.1f})",
                )

        return False, ""

    def get_run_metrics(self, run_id: str) -> RunMetrics | None:
        """Get metrics for a specific run."""
        return self._runs.get(run_id)

    def get_all_run_metrics(self) -> dict[str, RunMetrics]:
        """Get metrics for all runs."""
        return self._runs.copy()

    def get_aggregated_metrics(self) -> dict[str, Any]:
        """Get aggregated metrics across all runs."""
        with self._lock:
            total_tokens = sum(m.tokens.total_tokens for m in self._runs.values())
            total_input_tokens = sum(m.tokens.input_tokens for m in self._runs.values())
            total_output_tokens = sum(m.tokens.output_tokens for m in self._runs.values())
            total_cost = sum(m.estimated_cost_usd for m in self._runs.values())
            total_latency = sum(m.total_latency_ms for m in self._runs.values())

            model_usage: dict[str, dict[str, int]] = defaultdict(
                lambda: {"input": 0, "output": 0, "cost": 0.0}
            )
            for run in self._runs.values():
                if run.model:
                    model_usage[run.model]["input"] += run.tokens.input_tokens
                    model_usage[run.model]["output"] += run.tokens.output_tokens
                    model_usage[run.model]["cost"] += run.estimated_cost_usd

            tool_usage: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
            for run in self._runs.values():
                for node in run.nodes.values():
                    for tool_name, tool in node.tools.items():
                        tool_usage[tool_name]["calls"] += tool.call_count
                        tool_usage[tool_name]["errors"] += tool.error_count

            return {
                "total_runs": self._total_runs,
                "active_runs": len(self._active_runs),
                "successful_runs": self._total_runs_success,
                "failed_runs": self._total_runs_failed,
                "total_tokens": total_tokens,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_estimated_cost_usd": round(total_cost, 4),
                "total_latency_ms": total_latency,
                "model_usage": dict(model_usage),
                "tool_usage": dict(tool_usage),
            }

    def clear_run_metrics(self, run_id: str) -> bool:
        """Clear metrics for a specific run."""
        with self._lock:
            if run_id in self._runs:
                del self._runs[run_id]
            if run_id in self._run_samples:
                del self._run_samples[run_id]
            if run_id in self._active_runs:
                del self._active_runs[run_id]
            if run_id in self._consecutive_failures:
                del self._consecutive_failures[run_id]
            if run_id in self._baseline_burn_rate:
                del self._baseline_burn_rate[run_id]
            return True


_collector: FinOpsCollector | None = None
_collector_lock = threading.Lock()


def get_collector() -> FinOpsCollector:
    """Get the global FinOps collector instance."""
    global _collector
    with _collector_lock:
        if _collector is None:
            _collector = FinOpsCollector()
        return _collector


def reset_collector() -> None:
    """Reset the global collector (mainly for testing)."""
    global _collector
    with _collector_lock:
        _collector = None
