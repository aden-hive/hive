"""OpenTelemetry integration for distributed tracing and metrics.

Provides observability for the Hive framework:
- Distributed tracing across nodes and LLM calls
- Metrics collection (latency, tokens, errors)
- Log correlation with trace IDs
- Automatic span creation for key operations

Usage:
    from framework.telemetry import (
        init_telemetry,
        get_tracer,
        get_meter,
        trace_node,
        trace_llm_call,
    )

    # Initialize at startup
    init_telemetry(
        service_name="hive-agent",
        otlp_endpoint="http://localhost:4317",
    )

    # Use tracer for custom spans
    tracer = get_tracer()
    with tracer.start_as_current_span("my-operation"):
        ...

    # Use decorator for node tracing
    @trace_node
    async def execute(self, ctx: NodeContext) -> NodeResult:
        ...
"""

import functools
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ExporterType(StrEnum):
    """Telemetry exporter types."""

    CONSOLE = "console"
    OTLP = "otlp"
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"
    NONE = "none"


@dataclass
class TelemetryConfig:
    """Telemetry configuration."""

    # Service identity
    service_name: str = "hive-agent"
    service_version: str = "1.0.0"
    environment: str = "development"

    # Exporter settings
    trace_exporter: ExporterType = ExporterType.CONSOLE
    metrics_exporter: ExporterType = ExporterType.CONSOLE

    # OTLP endpoint (for OTLP exporter)
    otlp_endpoint: str = "http://localhost:4317"
    otlp_insecure: bool = True

    # Sampling
    trace_sample_rate: float = 1.0  # 100% sampling

    # Metrics
    metrics_export_interval: int = 60  # seconds

    # Additional attributes
    resource_attributes: dict[str, str] = field(default_factory=dict)


# Global state
_tracer = None
_meter = None
_initialized = False
_config: TelemetryConfig | None = None


class NoOpSpan:
    """No-op span for when OpenTelemetry is not available."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass


class NoOpTracer:
    """No-op tracer for when OpenTelemetry is not available."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield NoOpSpan()

    def start_span(self, name: str, **kwargs):
        return NoOpSpan()


class NoOpMeter:
    """No-op meter for when OpenTelemetry is not available."""

    def create_counter(self, name: str, **kwargs):
        return NoOpCounter()

    def create_histogram(self, name: str, **kwargs):
        return NoOpHistogram()

    def create_up_down_counter(self, name: str, **kwargs):
        return NoOpCounter()

    def create_observable_gauge(self, name: str, **kwargs):
        pass


class NoOpCounter:
    """No-op counter."""

    def add(self, amount: int, attributes: dict | None = None) -> None:
        pass


class NoOpHistogram:
    """No-op histogram."""

    def record(self, value: float, attributes: dict | None = None) -> None:
        pass


def init_telemetry(config: TelemetryConfig | None = None) -> None:
    """Initialize OpenTelemetry with the given configuration.

    Should be called once at application startup.
    """
    global _tracer, _meter, _initialized, _config

    if _initialized:
        logger.warning("Telemetry already initialized")
        return

    _config = config or TelemetryConfig()

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # Build resource
        resource_attrs = {
            "service.name": _config.service_name,
            "service.version": _config.service_version,
            "deployment.environment": _config.environment,
            **_config.resource_attributes,
        }
        resource = Resource.create(resource_attrs)

        # Set up tracer provider with sampling
        sampler = TraceIdRatioBased(_config.trace_sample_rate)
        tracer_provider = TracerProvider(resource=resource, sampler=sampler)

        # Add trace exporter
        if _config.trace_exporter == ExporterType.CONSOLE:
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )

            tracer_provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )
        elif _config.trace_exporter == ExporterType.OTLP:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(
                endpoint=_config.otlp_endpoint,
                insecure=_config.otlp_insecure,
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(tracer_provider)

        # Set up meter provider
        meter_provider = MeterProvider(resource=resource)

        # Add metrics exporter
        if _config.metrics_exporter == ExporterType.CONSOLE:
            from opentelemetry.sdk.metrics.export import (
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )

            reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=_config.metrics_export_interval * 1000,
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        elif _config.metrics_exporter == ExporterType.OTLP:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            exporter = OTLPMetricExporter(
                endpoint=_config.otlp_endpoint,
                insecure=_config.otlp_insecure,
            )
            reader = PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=_config.metrics_export_interval * 1000,
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[reader])

        metrics.set_meter_provider(meter_provider)

        # Get tracer and meter
        _tracer = trace.get_tracer(_config.service_name, _config.service_version)
        _meter = metrics.get_meter(_config.service_name, _config.service_version)

        _initialized = True
        logger.info(
            f"Telemetry initialized: service={_config.service_name}, "
            f"traces={_config.trace_exporter}, metrics={_config.metrics_exporter}"
        )

    except ImportError as e:
        logger.warning(
            f"OpenTelemetry not available ({e}). Using no-op instrumentation. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk"
        )
        _tracer = NoOpTracer()
        _meter = NoOpMeter()
        _initialized = True


def get_tracer():
    """Get the configured tracer instance."""
    if not _initialized:
        init_telemetry()
    return _tracer or NoOpTracer()


def get_meter():
    """Get the configured meter instance."""
    if not _initialized:
        init_telemetry()
    return _meter or NoOpMeter()


# =============================================================================
# Pre-defined metrics
# =============================================================================


class HiveMetrics:
    """Pre-defined metrics for the Hive framework."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_metrics()
        return cls._instance

    def _init_metrics(self):
        """Initialize all framework metrics."""
        meter = get_meter()

        # Node execution metrics
        self.node_executions = meter.create_counter(
            name="hive.node.executions",
            description="Total node executions",
            unit="1",
        )
        self.node_latency = meter.create_histogram(
            name="hive.node.latency",
            description="Node execution latency",
            unit="ms",
        )
        self.node_errors = meter.create_counter(
            name="hive.node.errors",
            description="Node execution errors",
            unit="1",
        )

        # LLM metrics
        self.llm_calls = meter.create_counter(
            name="hive.llm.calls",
            description="Total LLM API calls",
            unit="1",
        )
        self.llm_tokens_input = meter.create_counter(
            name="hive.llm.tokens.input",
            description="Total input tokens",
            unit="1",
        )
        self.llm_tokens_output = meter.create_counter(
            name="hive.llm.tokens.output",
            description="Total output tokens",
            unit="1",
        )
        self.llm_latency = meter.create_histogram(
            name="hive.llm.latency",
            description="LLM call latency",
            unit="ms",
        )
        self.llm_errors = meter.create_counter(
            name="hive.llm.errors",
            description="LLM call errors",
            unit="1",
        )

        # Tool metrics
        self.tool_calls = meter.create_counter(
            name="hive.tool.calls",
            description="Total tool calls",
            unit="1",
        )
        self.tool_latency = meter.create_histogram(
            name="hive.tool.latency",
            description="Tool call latency",
            unit="ms",
        )
        self.tool_errors = meter.create_counter(
            name="hive.tool.errors",
            description="Tool call errors",
            unit="1",
        )

        # Cache metrics
        self.cache_hits = meter.create_counter(
            name="hive.cache.hits",
            description="Cache hits",
            unit="1",
        )
        self.cache_misses = meter.create_counter(
            name="hive.cache.misses",
            description="Cache misses",
            unit="1",
        )

        # Graph execution metrics
        self.graph_executions = meter.create_counter(
            name="hive.graph.executions",
            description="Total graph executions",
            unit="1",
        )
        self.graph_steps = meter.create_histogram(
            name="hive.graph.steps",
            description="Steps per graph execution",
            unit="1",
        )


def get_metrics() -> HiveMetrics:
    """Get the singleton metrics instance."""
    return HiveMetrics()


# =============================================================================
# Decorators for easy instrumentation
# =============================================================================


def trace_node(func: F) -> F:
    """Decorator to trace node execution.

    Automatically creates a span with node metadata and records metrics.
    """

    @functools.wraps(func)
    async def wrapper(self, ctx, *args, **kwargs):
        tracer = get_tracer()
        metrics = get_metrics()

        span_name = f"node.{ctx.node_spec.name}"
        start_time = time.time()

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("node.id", ctx.node_id)
            span.set_attribute("node.name", ctx.node_spec.name)
            span.set_attribute("node.type", ctx.node_spec.node_type)

            try:
                result = await func(self, ctx, *args, **kwargs)

                # Record metrics
                latency_ms = (time.time() - start_time) * 1000
                metrics.node_executions.add(
                    1, {"node.name": ctx.node_spec.name, "success": str(result.success)}
                )
                metrics.node_latency.record(
                    latency_ms, {"node.name": ctx.node_spec.name}
                )

                span.set_attribute("node.success", result.success)
                if result.tokens_used:
                    span.set_attribute("node.tokens", result.tokens_used)

                return result

            except Exception as e:
                metrics.node_errors.add(
                    1, {"node.name": ctx.node_spec.name, "error.type": type(e).__name__}
                )
                span.record_exception(e)
                raise

    return wrapper


def trace_llm_call(func: F) -> F:
    """Decorator to trace LLM calls.

    Automatically creates a span with LLM metadata and records metrics.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        tracer = get_tracer()
        metrics = get_metrics()

        # Extract model from kwargs or args
        model = kwargs.get("model", "unknown")
        provider = kwargs.get("provider", "unknown")

        span_name = f"llm.{provider}.{model}"
        start_time = time.time()

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.provider", provider)

            try:
                result = await func(*args, **kwargs)

                # Record metrics
                latency_ms = (time.time() - start_time) * 1000
                metrics.llm_calls.add(1, {"model": model, "provider": provider})
                metrics.llm_latency.record(latency_ms, {"model": model})

                # Record token usage if available
                if hasattr(result, "input_tokens"):
                    metrics.llm_tokens_input.add(
                        result.input_tokens, {"model": model}
                    )
                    span.set_attribute("llm.tokens.input", result.input_tokens)
                if hasattr(result, "output_tokens"):
                    metrics.llm_tokens_output.add(
                        result.output_tokens, {"model": model}
                    )
                    span.set_attribute("llm.tokens.output", result.output_tokens)

                return result

            except Exception as e:
                metrics.llm_errors.add(
                    1, {"model": model, "error.type": type(e).__name__}
                )
                span.record_exception(e)
                raise

    return wrapper


def trace_tool_call(func: F) -> F:
    """Decorator to trace tool calls.

    Automatically creates a span with tool metadata and records metrics.
    """

    @functools.wraps(func)
    async def wrapper(tool_name: str, *args, **kwargs):
        tracer = get_tracer()
        metrics = get_metrics()

        span_name = f"tool.{tool_name}"
        start_time = time.time()

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("tool.name", tool_name)

            try:
                result = await func(tool_name, *args, **kwargs)

                # Record metrics
                latency_ms = (time.time() - start_time) * 1000
                metrics.tool_calls.add(1, {"tool.name": tool_name})
                metrics.tool_latency.record(latency_ms, {"tool.name": tool_name})

                return result

            except Exception as e:
                metrics.tool_errors.add(
                    1, {"tool.name": tool_name, "error.type": type(e).__name__}
                )
                span.record_exception(e)
                raise

    return wrapper


# =============================================================================
# Context propagation helpers
# =============================================================================


def get_current_trace_id() -> str | None:
    """Get the current trace ID for log correlation."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except ImportError:
        pass
    return None


def get_current_span_id() -> str | None:
    """Get the current span ID for log correlation."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, "016x")
    except ImportError:
        pass
    return None


def inject_trace_context() -> dict[str, str]:
    """Inject trace context for propagation to external services."""
    context = {}
    try:
        from opentelemetry.propagate import inject

        inject(context)
    except ImportError:
        pass
    return context


__all__ = [
    # Configuration
    "TelemetryConfig",
    "ExporterType",
    "init_telemetry",
    # Core APIs
    "get_tracer",
    "get_meter",
    "get_metrics",
    "HiveMetrics",
    # Decorators
    "trace_node",
    "trace_llm_call",
    "trace_tool_call",
    # Context
    "get_current_trace_id",
    "get_current_span_id",
    "inject_trace_context",
]
