"""Prometheus metrics exporter.

Exposes Hive agent metrics at a configurable HTTP endpoint for
Prometheus scraping.

Requires the ``observability`` optional dependency group::

    pip install framework[observability]

Usage::

    from framework.observability.exporters.prometheus import PrometheusExporter

    exporter = PrometheusExporter(port=9090)
    # Metrics available at http://localhost:9090/metrics

    runtime = Runtime(
        storage_path="./logs",
        observability_hooks=exporter,
    )
"""

from __future__ import annotations

import logging

try:
    from prometheus_client import Counter, Histogram, start_http_server

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class PrometheusExporter:
    """Exports Hive agent metrics to Prometheus.

    Metrics exposed:
    - ``hive_agent_runs_total`` — counter of runs by status
    - ``hive_node_duration_seconds`` — histogram of node latencies
    - ``hive_node_errors_total`` — counter of node errors
    - ``hive_llm_tokens_total`` — counter of tokens used
    - ``hive_decisions_total`` — counter of decisions made
    - ``hive_tool_calls_total`` — counter of tool calls

    Args:
        port: HTTP port for the metrics endpoint (default: 9090)
        start_server: If True, starts the HTTP server on init (default: True)
    """

    def __init__(self, port: int = 9090, start_server: bool = True) -> None:
        if not HAS_PROMETHEUS:
            raise ImportError(
                "prometheus-client is required for PrometheusExporter. "
                "Install with: pip install prometheus-client"
            )

        # Counters
        self._runs_total = Counter(
            "hive_agent_runs_total",
            "Total number of agent runs",
            ["status"],
        )
        self._node_errors_total = Counter(
            "hive_node_errors_total",
            "Total number of node errors",
            ["node_id", "node_type"],
        )
        self._tokens_total = Counter(
            "hive_llm_tokens_total",
            "Total LLM tokens used",
            ["node_id"],
        )
        self._decisions_total = Counter(
            "hive_decisions_total",
            "Total decisions made",
        )
        self._tool_calls_total = Counter(
            "hive_tool_calls_total",
            "Total tool calls",
            ["tool_name", "is_error"],
        )

        # Histograms
        self._node_duration = Histogram(
            "hive_node_duration_seconds",
            "Node execution duration in seconds",
            ["node_id", "node_type"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )

        if start_server:
            try:
                start_http_server(port)
                logger.info("Prometheus metrics server started on port %d", port)
            except OSError as e:
                logger.warning("Could not start Prometheus server on port %d: %s", port, e)

    async def on_run_start(self, event: RunStartEvent) -> None:
        pass  # No metric on start — counted on complete

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        self._runs_total.labels(status=event.status).inc()

    async def on_node_start(self, event: NodeStartEvent) -> None:
        pass  # No metric on start — measured on complete

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        self._node_duration.labels(
            node_id=event.node_id, node_type=event.node_type
        ).observe(event.latency_ms / 1000.0)

        if event.tokens_used:
            self._tokens_total.labels(node_id=event.node_id).inc(event.tokens_used)

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        self._node_errors_total.labels(
            node_id=event.node_id, node_type=event.node_type
        ).inc()

    async def on_decision_made(self, event: DecisionEvent) -> None:
        self._decisions_total.inc()

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        self._tool_calls_total.labels(
            tool_name=event.tool_name,
            is_error=str(event.is_error).lower(),
        ).inc()
