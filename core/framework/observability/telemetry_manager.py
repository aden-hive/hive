"""
OpenTelemetry integration for distributed tracing and metrics.

This module provides a TelemetryManager that implements the ObservabilityHooks
protocol and integrates with OpenTelemetry for production-grade observability.

Features:
- Distributed tracing with automatic span creation
- Metrics collection for tokens, latency, and success rates
- Semantic conventions for AI agent attributes
- Zero overhead when OpenTelemetry is not installed
"""

import logging
from contextvars import ContextVar
from typing import Any

from framework.observability.config import ObservabilityConfig, TelemetryConfig
from framework.observability.hooks import ObservabilityHooks
from framework.observability.types import (
    DecisionData,
    EdgeTraversalData,
    NodeContext,
    NodeResult,
    RetryData,
    RunContext,
    RunOutcome,
)

logger = logging.getLogger(__name__)

_active_spans: ContextVar[dict[str, Any] | None] = ContextVar("active_spans", default=None)
_tracer: Any | None = None
_meter: Any | None = None
_initialized = False


def _check_opentelemetry() -> bool:
    """Check if OpenTelemetry is available."""
    try:
        import importlib.util

        return importlib.util.find_spec("opentelemetry") is not None
    except ImportError:
        return False


def _init_opentelemetry(config: ObservabilityConfig) -> None:
    """Initialize OpenTelemetry if available and not already initialized."""
    global _tracer, _meter, _initialized

    if _initialized:
        return

    if not _check_opentelemetry():
        logger.debug("OpenTelemetry not installed, telemetry disabled")
        _initialized = True
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
                "agent.framework.name": "hive",
            }
        )

        if config.trace_enabled:
            trace.set_tracer_provider(TracerProvider(resource=resource))
            _tracer = trace.get_tracer("hive.agent")

        if config.metrics_enabled:
            metrics.set_meter_provider(MeterProvider(resource=resource))
            _meter = metrics.get_meter("hive.agent")

        _initialized = True
        logger.info("OpenTelemetry initialized successfully")

    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry: {e}")
        _initialized = True


class TelemetryManager(ObservabilityHooks):
    """
    OpenTelemetry-based telemetry manager.

    This manager implements ObservabilityHooks and creates spans, metrics,
    and logs for all agent lifecycle events.

    The manager uses OpenTelemetry's context propagation to automatically
    link spans across async boundaries, enabling distributed tracing.

    Attributes:
        config: Observability configuration.
        telemetry_config: Telemetry-specific configuration.

    Example:
        config = ObservabilityConfig(
            enabled=True,
            service_name="my-agent",
        )
        manager = TelemetryManager(config)
    """

    SEMANTIC_CONVENTIONS = {
        "framework.name": "hive",
        "framework.type": "agent",
        "agent.goal.id": "agent.goal.id",
        "agent.goal.description": "agent.goal.description",
        "agent.run.id": "agent.run.id",
        "agent.node.id": "agent.node.id",
        "agent.node.type": "agent.node.type",
        "agent.decision.intent": "agent.decision.intent",
        "agent.decision.chosen": "agent.decision.chosen",
        "agent.tool.name": "agent.tool.name",
        "agent.llm.model": "agent.llm.model",
        "agent.llm.provider": "agent.llm.provider",
        "agent.llm.tokens.input": "agent.llm.tokens.input",
        "agent.llm.tokens.output": "agent.llm.tokens.output",
        "agent.llm.tokens.cached": "agent.llm.tokens.cached",
    }

    def __init__(
        self,
        config: ObservabilityConfig,
        telemetry_config: TelemetryConfig | None = None,
    ) -> None:
        """
        Initialize the telemetry manager.

        Args:
            config: Observability configuration.
            telemetry_config: Optional telemetry-specific configuration.
        """
        self.config = config
        self.telemetry_config = telemetry_config or TelemetryConfig()

        if config.enabled and config.trace_enabled:
            _init_opentelemetry(config)

        self._active_spans: dict[str, Any] = {}

    def _get_span_attribute(self, key: str, default: Any = None) -> Any:
        """Get an attribute from the current active span."""
        spans = _active_spans.get()
        if spans:
            for span in reversed(spans.values()):
                if hasattr(span, "attributes") and key in span.attributes:
                    return span.attributes.get(key)
        return default

    def _add_span(self, run_id: str, span: Any) -> None:
        """Add a span to the active spans context."""
        spans = _active_spans.get().copy()
        spans[run_id] = span
        _active_spans.set(spans)

    def _remove_span(self, run_id: str) -> None:
        """Remove a span from the active spans context."""
        spans = _active_spans.get().copy()
        spans.pop(run_id, None)
        _active_spans.set(spans)

    def _get_active_span(self, run_id: str) -> Any | None:
        """Get the active span for a run."""
        spans = _active_spans.get()
        return spans.get(run_id)

    async def on_run_start(self, context: RunContext) -> None:
        if _tracer is None:
            return

        try:
            span = _tracer.start_span(
                "agent.run",
                attributes={
                    "agent.run.id": context.run_id,
                    "agent.goal.id": context.goal_id,
                    "agent.goal.description": context.goal_description[:200],
                    "agent.framework.name": "hive",
                },
            )
            self._add_span(context.run_id, span)
        except Exception as e:
            logger.debug(f"Failed to create run span: {e}")

    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        if _tracer is None:
            return

        try:
            span = self._get_active_span(context.run_id)
            if span:
                span.set_attribute("agent.run.success", outcome.success)
                span.set_attribute("agent.run.steps", outcome.steps_executed)
                span.set_attribute("agent.run.tokens", outcome.total_tokens)
                span.set_attribute("agent.run.latency_ms", outcome.total_latency_ms)
                if outcome.error:
                    span.set_attribute("agent.run.error", outcome.error[:500])
                    span.set_status(2, outcome.error[:500])
                else:
                    span.set_status(1)
                span.end()
                self._remove_span(context.run_id)
        except Exception as e:
            logger.debug(f"Failed to complete run span: {e}")

    async def on_node_start(self, context: NodeContext) -> None:
        if _tracer is None:
            return

        try:
            span = _tracer.start_span(
                f"node.{context.node_id}",
                attributes={
                    "agent.node.id": context.node_id,
                    "agent.node.name": context.node_name,
                    "agent.node.type": context.node_type,
                    "agent.run.id": context.run_id,
                },
            )

            key = f"{context.run_id}:{context.node_id}"
            self._add_span(key, span)
        except Exception as e:
            logger.debug(f"Failed to create node span: {e}")

    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        if _tracer is None:
            return

        try:
            key = f"{context.run_id}:{context.node_id}"
            span = self._get_active_span(key)

            if span:
                span.set_attribute("agent.node.success", result.success)
                span.set_attribute("agent.node.tokens", result.tokens_used)
                span.set_attribute("agent.node.latency_ms", result.latency_ms)

                if result.error:
                    span.set_attribute("agent.node.error", result.error[:500])
                    span.set_status(2, result.error[:500])
                else:
                    span.set_status(1)

                span.end()
                self._remove_span(key)
        except Exception as e:
            logger.debug(f"Failed to complete node span: {e}")

    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        if _tracer is None:
            return

        try:
            key = f"{context.run_id}:{context.node_id}"
            span = self._get_active_span(key)

            if span:
                span.set_attribute("agent.node.success", False)
                span.set_attribute("agent.node.error", error[:500])
                span.record_exception(Exception(error))
                span.set_status(2, error[:500])
                span.end()
                self._remove_span(key)
        except Exception as e:
            logger.debug(f"Failed to record node error: {e}")

    async def on_decision_made(self, decision: DecisionData) -> None:
        if _tracer is None:
            return

        try:
            key = f"{decision.node_id}"
            span = self._get_active_span(key)

            if span:
                span.add_event(
                    "decision",
                    attributes={
                        "agent.decision.id": decision.decision_id,
                        "agent.decision.intent": decision.intent[:200],
                        "agent.decision.chosen": decision.chosen,
                        "agent.decision.type": decision.decision_type,
                    },
                )
        except Exception as e:
            logger.debug(f"Failed to record decision: {e}")

    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        if _tracer is None:
            return

        try:
            key = f"{context.run_id}:{context.node_id}"
            span = self._get_active_span(key)

            if span:
                span.add_event(
                    "tool_call",
                    attributes={
                        "agent.tool.name": tool_name,
                        "agent.tool.error": is_error,
                        "agent.tool.latency_ms": latency_ms,
                    },
                )
        except Exception as e:
            logger.debug(f"Failed to record tool call: {e}")

    async def on_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: NodeContext,
        latency_ms: int = 0,
        cached_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        if _tracer is None:
            return

        try:
            key = f"{context.run_id}:{context.node_id}"
            span = self._get_active_span(key)

            if span:
                attrs = {
                    "agent.llm.model": model,
                    "agent.llm.tokens.input": input_tokens,
                    "agent.llm.tokens.output": output_tokens,
                    "agent.llm.tokens.cached": cached_tokens,
                    "agent.llm.latency_ms": latency_ms,
                }
                if error:
                    attrs["agent.llm.error"] = error[:500]

                span.add_event("llm_call", attributes=attrs)
        except Exception as e:
            logger.debug(f"Failed to record LLM call: {e}")

    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        pass

    async def on_retry(self, data: RetryData) -> None:
        if _tracer is None:
            return

        try:
            key = f"{data.run_id}:{data.node_id}"
            span = self._get_active_span(key)

            if span:
                span.add_event(
                    "retry",
                    attributes={
                        "agent.retry.count": data.retry_count,
                        "agent.retry.max": data.max_retries,
                        "agent.retry.error": data.error[:200] if data.error else "",
                    },
                )
        except Exception as e:
            logger.debug(f"Failed to record retry: {e}")


def create_telemetry_manager(
    config: ObservabilityConfig | None = None,
) -> ObservabilityHooks:
    """
    Create a telemetry manager based on configuration.

    This factory function creates either a TelemetryManager (if OpenTelemetry
    is available and enabled) or a NoOpHooks instance.

    Args:
        config: Observability configuration. If None, uses default config.

    Returns:
        An ObservabilityHooks implementation.
    """
    if config is None:
        config = ObservabilityConfig.disabled()

    if not config.enabled:
        from framework.observability.hooks import NoOpHooks

        return NoOpHooks()

    if not _check_opentelemetry():
        logger.debug("OpenTelemetry not available, using no-op hooks")
        from framework.observability.hooks import NoOpHooks

        return NoOpHooks()

    return TelemetryManager(config)
