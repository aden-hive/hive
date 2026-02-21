"""OpenTelemetry integration for Hive agents.

Provides:
- OTLP trace export
- OTLP metrics export
- Automatic span creation for runs, nodes, and tool calls
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from framework.finops.config import FinOpsConfig

if TYPE_CHECKING:
    from framework.finops.metrics import FinOpsCollector

logger = logging.getLogger(__name__)

_otel_initialized = False
_tracer = None
_meter = None

OTEL_AVAILABLE = False
try:
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    pass


def is_otel_available() -> bool:
    """Check if OpenTelemetry is available."""
    return OTEL_AVAILABLE


def init_otel(config: FinOpsConfig | None = None) -> bool:
    """Initialize OpenTelemetry with OTLP exporters.

    Args:
        config: FinOps configuration

    Returns:
        True if initialized successfully, False otherwise
    """
    global _otel_initialized, _tracer, _meter

    if _otel_initialized:
        return True

    if not OTEL_AVAILABLE:
        logger.warning(
            "OpenTelemetry not available. Install with: pip install opentelemetry-api opentelemetry-sdk"
        )
        return False

    config = config or FinOpsConfig.from_env()

    if not config.otel_enabled:
        return False

    endpoint = config.otel_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set, OpenTelemetry disabled")
        return False

    try:
        resource = Resource.create(
            {
                "service.name": config.otel_service_name,
                "service.version": "1.0.0",
            }
        )

        tracer_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(endpoint=endpoint)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer(config.otel_service_name)

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint),
            export_interval_millis=60000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter(config.otel_service_name)

        _otel_initialized = True
        logger.info(f"OpenTelemetry initialized with endpoint: {endpoint}")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return False


def get_tracer():
    """Get the OpenTelemetry tracer."""
    if not _otel_initialized:
        init_otel()
    return _tracer


def get_meter():
    """Get the OpenTelemetry meter."""
    if not _otel_initialized:
        init_otel()
    return _meter


@contextmanager
def start_run_span(
    run_id: str,
    agent_id: str = "",
    goal_id: str = "",
    model: str = "",
):
    """Context manager for a run span.

    Args:
        run_id: Run identifier
        agent_id: Agent identifier
        goal_id: Goal identifier
        model: Model name
    """
    if not OTEL_AVAILABLE or not _tracer:
        yield None
        return

    with _tracer.start_as_current_span(
        "hive.run",
        attributes={
            "hive.run_id": run_id,
            "hive.agent_id": agent_id,
            "hive.goal_id": goal_id,
            "hive.model": model,
        },
    ) as span:
        yield span


@contextmanager
def start_node_span(
    run_id: str,
    node_id: str,
    node_type: str = "",
):
    """Context manager for a node span.

    Args:
        run_id: Run identifier
        node_id: Node identifier
        node_type: Node type
    """
    if not OTEL_AVAILABLE or not _tracer:
        yield None
        return

    with _tracer.start_as_current_span(
        "hive.node",
        attributes={
            "hive.run_id": run_id,
            "hive.node_id": node_id,
            "hive.node_type": node_type,
        },
    ) as span:
        yield span


@contextmanager
def start_tool_span(
    run_id: str,
    node_id: str,
    tool_name: str,
):
    """Context manager for a tool call span.

    Args:
        run_id: Run identifier
        node_id: Node identifier
        tool_name: Tool name
    """
    if not OTEL_AVAILABLE or not _tracer:
        yield None
        return

    with _tracer.start_as_current_span(
        "hive.tool_call",
        attributes={
            "hive.run_id": run_id,
            "hive.node_id": node_id,
            "hive.tool_name": tool_name,
        },
    ) as span:
        yield span


def record_token_metrics(
    run_id: str,
    node_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float = 0.0,
) -> None:
    """Record token metrics to OpenTelemetry.

    Args:
        run_id: Run identifier
        node_id: Node identifier
        model: Model name
        input_tokens: Input token count
        output_tokens: Output token count
        estimated_cost_usd: Estimated cost in USD
    """
    if not OTEL_AVAILABLE or not _meter:
        return

    input_counter = _meter.create_counter(
        "hive_tokens_input",
        description="Input tokens consumed",
        unit="tokens",
    )
    output_counter = _meter.create_counter(
        "hive_tokens_output",
        description="Output tokens generated",
        unit="tokens",
    )
    cost_counter = _meter.create_counter(
        "hive_estimated_cost_usd",
        description="Estimated cost in USD (multiplied by 1M for precision)",
        unit="usd",
    )

    labels = {
        "run_id": run_id,
        "node_id": node_id,
        "model": model,
    }

    input_counter.add(input_tokens, labels)
    output_counter.add(output_tokens, labels)
    cost_counter.add(int(estimated_cost_usd * 1_000_000), labels)


def record_run_metrics(
    run_id: str,
    agent_id: str,
    success: bool,
    total_tokens: int,
    estimated_cost_usd: float,
    duration_ms: int,
) -> None:
    """Record run-level metrics to OpenTelemetry.

    Args:
        run_id: Run identifier
        agent_id: Agent identifier
        success: Whether the run succeeded
        total_tokens: Total tokens consumed
        estimated_cost_usd: Estimated cost in USD
        duration_ms: Run duration in milliseconds
    """
    if not OTEL_AVAILABLE or not _meter:
        return

    run_counter = _meter.create_counter(
        "hive_runs_total",
        description="Total number of runs",
        unit="runs",
    )

    token_histogram = _meter.create_histogram(
        "hive_tokens_per_run",
        description="Tokens consumed per run",
        unit="tokens",
    )

    cost_histogram = _meter.create_histogram(
        "hive_cost_per_run_usd",
        description="Estimated cost per run in USD (multiplied by 1M for precision)",
        unit="usd",
    )

    duration_histogram = _meter.create_histogram(
        "hive_run_duration_ms",
        description="Run duration in milliseconds",
        unit="ms",
    )

    labels = {
        "run_id": run_id,
        "agent_id": agent_id,
        "success": str(success).lower(),
    }

    run_counter.add(1, labels)
    token_histogram.record(total_tokens, labels)
    cost_histogram.record(int(estimated_cost_usd * 1_000_000), labels)
    duration_histogram.record(duration_ms, labels)


def record_budget_alert(
    run_id: str,
    policy_name: str,
    action: str,
    threshold: float,
    current_value: float,
) -> None:
    """Record a budget policy alert.

    Args:
        run_id: Run identifier
        policy_name: Name of the triggered policy
        action: Action taken (warn, degrade, throttle, kill)
        threshold: Threshold value
        current_value: Current value that triggered the alert
    """
    if not OTEL_AVAILABLE or not _meter:
        return

    alert_counter = _meter.create_counter(
        "hive_budget_alerts_total",
        description="Total number of budget policy alerts",
        unit="alerts",
    )

    labels = {
        "run_id": run_id,
        "policy_name": policy_name,
        "action": action,
    }

    alert_counter.add(1, labels)

    if _tracer:
        with _tracer.start_as_current_span(
            "hive.budget_alert",
            attributes={
                "hive.run_id": run_id,
                "hive.policy_name": policy_name,
                "hive.action": action,
                "hive.threshold": threshold,
                "hive.current_value": current_value,
            },
        ):
            pass


def record_runaway_detection(
    run_id: str,
    reason: str,
) -> None:
    """Record a runaway loop detection event.

    Args:
        run_id: Run identifier
        reason: Reason for the detection
    """
    if not OTEL_AVAILABLE or not _meter:
        return

    runaway_counter = _meter.create_counter(
        "hive_runaway_detected_total",
        description="Total number of runaway loop detections",
        unit="detections",
    )

    labels = {
        "run_id": run_id,
        "reason": reason[:100],
    }

    runaway_counter.add(1, labels)

    if _tracer:
        with _tracer.start_as_current_span(
            "hive.runaway_detected",
            attributes={
                "hive.run_id": run_id,
                "hive.reason": reason,
            },
        ):
            pass
