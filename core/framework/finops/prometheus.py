"""Prometheus metrics exporter for Hive agents.

Provides a /metrics endpoint for Prometheus scraping with:
- Token usage metrics (input/output by model, node, tool)
- Cost estimation metrics
- Run lifecycle metrics
- Burn rate and runaway detection metrics
- Budget policy metrics
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from framework.finops.config import FinOpsConfig

if TYPE_CHECKING:
    from framework.finops.metrics import FinOpsCollector

logger = logging.getLogger(__name__)

PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        registry,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    pass

_metrics_initialized = False
_metrics: dict[str, Any] = {}


def is_prometheus_available() -> bool:
    """Check if prometheus_client is available."""
    return PROMETHEUS_AVAILABLE


class PrometheusMetrics:
    """Prometheus metrics for Hive agents."""

    def __init__(self, namespace: str = "hive"):
        self.namespace = namespace
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize all Prometheus metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        self.runs_total = Counter(
            f"{self.namespace}_runs_total",
            "Total number of runs",
            ["agent_id", "status"],
        )

        self.runs_active = Gauge(
            f"{self.namespace}_runs_active",
            "Number of currently active runs",
            ["agent_id"],
        )

        self.run_duration_seconds = Histogram(
            f"{self.namespace}_run_duration_seconds",
            "Run duration in seconds",
            ["agent_id"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
        )

        self.tokens_input_total = Counter(
            f"{self.namespace}_tokens_input_total",
            "Total input tokens consumed",
            ["agent_id", "model", "node_id"],
        )

        self.tokens_output_total = Counter(
            f"{self.namespace}_tokens_output_total",
            "Total output tokens generated",
            ["agent_id", "model", "node_id"],
        )

        self.tokens_cache_write_total = Counter(
            f"{self.namespace}_tokens_cache_write_total",
            "Total cache write tokens",
            ["agent_id", "model", "node_id"],
        )

        self.tokens_cache_read_total = Counter(
            f"{self.namespace}_tokens_cache_read_total",
            "Total cache read tokens",
            ["agent_id", "model", "node_id"],
        )

        self.estimated_cost_usd_total = Counter(
            f"{self.namespace}_estimated_cost_usd_total",
            "Total estimated cost in USD",
            ["agent_id", "model"],
        )

        self.cost_per_run_usd = Histogram(
            f"{self.namespace}_cost_per_run_usd",
            "Estimated cost per run in USD",
            ["agent_id"],
            buckets=[0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )

        self.burn_rate_tokens_per_min = Gauge(
            f"{self.namespace}_burn_rate_tokens_per_min",
            "Current token burn rate per minute",
            ["run_id", "agent_id"],
        )

        self.nodes_executed_total = Counter(
            f"{self.namespace}_nodes_executed_total",
            "Total node executions",
            ["agent_id", "node_type", "success"],
        )

        self.node_latency_seconds = Histogram(
            f"{self.namespace}_node_latency_seconds",
            "Node execution latency in seconds",
            ["agent_id", "node_id"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        )

        self.node_retries_total = Counter(
            f"{self.namespace}_node_retries_total",
            "Total node retries",
            ["agent_id", "node_id"],
        )

        self.tool_calls_total = Counter(
            f"{self.namespace}_tool_calls_total",
            "Total tool calls",
            ["agent_id", "tool_name", "is_error"],
        )

        self.tool_latency_seconds = Histogram(
            f"{self.namespace}_tool_latency_seconds",
            "Tool call latency in seconds",
            ["agent_id", "tool_name"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
        )

        self.runaway_detected_total = Counter(
            f"{self.namespace}_runaway_detected_total",
            "Total runaway loop detections",
            ["agent_id", "reason"],
        )

        self.budget_alerts_total = Counter(
            f"{self.namespace}_budget_alerts_total",
            "Total budget policy alerts",
            ["agent_id", "policy_name", "action"],
        )

        self.budget_threshold_percentage = Gauge(
            f"{self.namespace}_budget_threshold_percentage",
            "Current budget usage as percentage of threshold",
            ["agent_id", "policy_name", "scope"],
        )

        self.info = Info(
            f"{self.namespace}_finops",
            "FinOps configuration information",
        )
        self.info.info({"version": "1.0.0", "module": "finops"})

    def record_run_start(self, agent_id: str) -> None:
        """Record a run start event."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.runs_active.labels(agent_id=agent_id).inc()

    def record_run_end(
        self,
        agent_id: str,
        success: bool,
        duration_seconds: float,
        cost_usd: float,
    ) -> None:
        """Record a run end event."""
        if not PROMETHEUS_AVAILABLE:
            return

        status = "success" if success else "failure"
        self.runs_total.labels(agent_id=agent_id, status=status).inc()
        self.runs_active.labels(agent_id=agent_id).dec()
        self.run_duration_seconds.labels(agent_id=agent_id).observe(duration_seconds)
        self.cost_per_run_usd.labels(agent_id=agent_id).observe(cost_usd)

    def record_tokens(
        self,
        agent_id: str,
        model: str,
        node_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record token usage."""
        if not PROMETHEUS_AVAILABLE:
            return

        self.tokens_input_total.labels(agent_id=agent_id, model=model, node_id=node_id).inc(
            input_tokens
        )
        self.tokens_output_total.labels(agent_id=agent_id, model=model, node_id=node_id).inc(
            output_tokens
        )

        if cache_write_tokens:
            self.tokens_cache_write_total.labels(
                agent_id=agent_id, model=model, node_id=node_id
            ).inc(cache_write_tokens)
        if cache_read_tokens:
            self.tokens_cache_read_total.labels(
                agent_id=agent_id, model=model, node_id=node_id
            ).inc(cache_read_tokens)
        if cost_usd:
            self.estimated_cost_usd_total.labels(agent_id=agent_id, model=model).inc(cost_usd)

    def record_burn_rate(self, run_id: str, agent_id: str, tokens_per_min: float) -> None:
        """Record current burn rate."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.burn_rate_tokens_per_min.labels(run_id=run_id, agent_id=agent_id).set(tokens_per_min)

    def record_node_execution(
        self,
        agent_id: str,
        node_id: str,
        node_type: str,
        success: bool,
        latency_seconds: float,
        retries: int = 0,
    ) -> None:
        """Record a node execution."""
        if not PROMETHEUS_AVAILABLE:
            return

        self.nodes_executed_total.labels(
            agent_id=agent_id, node_type=node_type, success=str(success).lower()
        ).inc()
        self.node_latency_seconds.labels(agent_id=agent_id, node_id=node_id).observe(
            latency_seconds
        )
        if retries:
            self.node_retries_total.labels(agent_id=agent_id, node_id=node_id).inc(retries)

    def record_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        is_error: bool,
        latency_seconds: float,
    ) -> None:
        """Record a tool call."""
        if not PROMETHEUS_AVAILABLE:
            return

        self.tool_calls_total.labels(
            agent_id=agent_id, tool_name=tool_name, is_error=str(is_error).lower()
        ).inc()
        self.tool_latency_seconds.labels(agent_id=agent_id, tool_name=tool_name).observe(
            latency_seconds
        )

    def record_runaway_detection(self, agent_id: str, reason: str) -> None:
        """Record a runaway loop detection."""
        if not PROMETHEUS_AVAILABLE:
            return
        self.runaway_detected_total.labels(agent_id=agent_id, reason=reason[:100]).inc()

    def record_budget_alert(
        self,
        agent_id: str,
        policy_name: str,
        action: str,
        threshold_percentage: float,
    ) -> None:
        """Record a budget policy alert."""
        if not PROMETHEUS_AVAILABLE:
            return

        self.budget_alerts_total.labels(
            agent_id=agent_id, policy_name=policy_name, action=action
        ).inc()
        self.budget_threshold_percentage.labels(
            agent_id=agent_id, policy_name=policy_name, scope="run"
        ).set(threshold_percentage)


class PrometheusExporter:
    """Prometheus HTTP exporter for Hive metrics.

    Provides an HTTP server with a /metrics endpoint for Prometheus scraping.
    """

    def __init__(
        self,
        collector: "FinOpsCollector | None" = None,
        config: FinOpsConfig | None = None,
    ):
        self.config = config or FinOpsConfig.from_env()
        self.collector = collector
        self.metrics = PrometheusMetrics() if PROMETHEUS_AVAILABLE else None
        self._server = None
        self._running = False
        self._thread: threading.Thread | None = None

    def set_collector(self, collector: "FinOpsCollector") -> None:
        """Set the FinOps collector to use."""
        self.collector = collector

    def start(self) -> bool:
        """Start the Prometheus HTTP server."""
        if not PROMETHEUS_AVAILABLE:
            logger.warning(
                "prometheus_client not available. Install with: pip install prometheus-client"
            )
            return False

        if not self.config.prometheus_enabled:
            return False

        if self._running:
            return True

        try:
            from prometheus_client import start_http_server

            port = self.config.prometheus_port
            host = self.config.prometheus_host

            start_http_server(port, addr=host, registry=registry)
            self._running = True
            logger.info(f"Prometheus metrics server started on {host}:{port}")
            return True

        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")
            return False

    def stop(self) -> None:
        """Stop the Prometheus HTTP server."""
        self._running = False

    def get_metrics(self) -> bytes:
        """Get the latest metrics in Prometheus format."""
        if not PROMETHEUS_AVAILABLE:
            return b"# prometheus_client not available\n"
        return generate_latest(registry)

    def update_from_collector(self) -> None:
        """Update metrics from the collector."""
        if not self.collector or not self.metrics:
            return

        agg = self.collector.get_aggregated_metrics()

        for run_id, run_metrics in self.collector.get_all_run_metrics().items():
            agent_id = run_metrics.agent_id or "unknown"

            burn_rate = self.collector.get_burn_rate(run_id)
            if burn_rate > 0:
                self.metrics.record_burn_rate(run_id, agent_id, burn_rate)


_prometheus_exporter: PrometheusExporter | None = None
_exporter_lock = threading.Lock()


def get_prometheus_exporter(
    collector: "FinOpsCollector | None" = None,
    config: FinOpsConfig | None = None,
) -> PrometheusExporter:
    """Get the global Prometheus exporter instance."""
    global _prometheus_exporter
    with _exporter_lock:
        if _prometheus_exporter is None:
            _prometheus_exporter = PrometheusExporter(collector, config)
        elif collector:
            _prometheus_exporter.set_collector(collector)
        return _prometheus_exporter


def get_metrics() -> PrometheusMetrics | None:
    """Get the Prometheus metrics instance."""
    exporter = get_prometheus_exporter()
    return exporter.metrics


def start_prometheus_server(
    collector: "FinOpsCollector | None" = None,
    config: FinOpsConfig | None = None,
) -> bool:
    """Start the Prometheus metrics server.

    Args:
        collector: FinOps collector instance
        config: FinOps configuration

    Returns:
        True if server started successfully
    """
    exporter = get_prometheus_exporter(collector, config)
    return exporter.start()


def reset_prometheus() -> None:
    """Reset the global exporter (mainly for testing)."""
    global _prometheus_exporter
    with _exporter_lock:
        if _prometheus_exporter:
            _prometheus_exporter.stop()
        _prometheus_exporter = None
