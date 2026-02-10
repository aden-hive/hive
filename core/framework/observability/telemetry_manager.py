"""OpenTelemetry-backed implementation of ObservabilityHooks.

``TelemetryManager`` translates lifecycle events into OTel spans and metrics.
Each agent run becomes a root span, each node becomes a child span, and
counters/histograms track key operational metrics.

Requires the ``observability`` optional dependency group::

    pip install framework[observability]

If OpenTelemetry is not installed, importing this module raises
``ImportError`` — callers should gate usage behind a try/except or
the ``ObservabilityConfig.enabled`` flag.

Usage::

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    manager = TelemetryManager(tracer_provider=provider)

    runtime = Runtime(
        storage_path="./logs",
        observability_hooks=manager,
    )
"""

from __future__ import annotations

import logging
import threading
from typing import Any

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import StatusCode

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

from framework.observability import semantic_conventions as sc
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


class TelemetryManager:
    """Maps ObservabilityHooks events to OpenTelemetry spans and metrics.

    Lifecycle mapping:
    - ``on_run_start``   → starts root span ``agent.run``
    - ``on_node_start``  → starts child span ``node.execute``
    - ``on_node_complete`` → closes child span with OK status
    - ``on_node_error``  → closes child span with ERROR status
    - ``on_run_complete`` → closes root span

    All spans carry Hive semantic convention attributes.
    """

    def __init__(
        self,
        tracer_provider: Any | None = None,
        service_name: str = "hive-agent",
    ) -> None:
        if not HAS_OTEL:
            raise ImportError(
                "OpenTelemetry packages are required for TelemetryManager. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk"
            )

        if tracer_provider is None:
            tracer_provider = TracerProvider()

        self._tracer = trace.get_tracer(
            instrumenting_module_name="framework.observability",
            tracer_provider=tracer_provider,
        )
        self._service_name = service_name

        # Active span tracking: run_id → span, (run_id, node_id) → span
        self._lock = threading.Lock()
        self._run_spans: dict[str, trace.Span] = {}
        self._node_spans: dict[tuple[str, str], trace.Span] = {}
        self._run_contexts: dict[str, Any] = {}

    # -- Run lifecycle --

    async def on_run_start(self, event: RunStartEvent) -> None:
        span = self._tracer.start_span(
            name=sc.SPAN_AGENT_RUN,
            attributes={
                sc.ATTR_FRAMEWORK_NAME: sc.FRAMEWORK_NAME,
                sc.ATTR_RUN_ID: event.run_id,
                sc.ATTR_GOAL_ID: event.goal_id,
            },
        )
        ctx = trace.set_span_in_context(span)
        token = otel_context.attach(ctx)
        with self._lock:
            self._run_spans[event.run_id] = span
            self._run_contexts[event.run_id] = (ctx, token)

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        with self._lock:
            span = self._run_spans.pop(event.run_id, None)
            ctx_data = self._run_contexts.pop(event.run_id, None)
        if span is None:
            return

        span.set_attribute(sc.ATTR_RUN_STATUS, event.status)
        span.set_attribute(sc.ATTR_RUN_DURATION_MS, event.duration_ms)

        if event.status == "success":
            span.set_status(StatusCode.OK)
        else:
            span.set_status(StatusCode.ERROR, event.status)

        span.end()

        if ctx_data:
            _, token = ctx_data
            otel_context.detach(token)

    # -- Node lifecycle --

    async def on_node_start(self, event: NodeStartEvent) -> None:
        with self._lock:
            parent_ctx_data = self._run_contexts.get(event.run_id)
        parent_ctx = parent_ctx_data[0] if parent_ctx_data else None

        span = self._tracer.start_span(
            name=f"{sc.SPAN_NODE_EXECUTE}.{event.node_id}",
            context=parent_ctx,
            attributes={
                sc.ATTR_NODE_ID: event.node_id,
                sc.ATTR_NODE_NAME: event.node_name,
                sc.ATTR_NODE_TYPE: event.node_type,
            },
        )
        with self._lock:
            self._node_spans[(event.run_id, event.node_id)] = span

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        with self._lock:
            span = self._node_spans.pop((event.run_id, event.node_id), None)
        if span is None:
            return

        span.set_attribute(sc.ATTR_NODE_SUCCESS, event.success)
        span.set_attribute(sc.ATTR_NODE_LATENCY_MS, event.latency_ms)
        if event.tokens_used:
            span.set_attribute(sc.ATTR_LLM_TOKENS_TOTAL, event.tokens_used)
        if event.input_tokens:
            span.set_attribute(sc.ATTR_LLM_TOKENS_INPUT, event.input_tokens)
        if event.output_tokens:
            span.set_attribute(sc.ATTR_LLM_TOKENS_OUTPUT, event.output_tokens)

        if event.success:
            span.set_status(StatusCode.OK)
        else:
            span.set_status(StatusCode.ERROR, "Node execution failed")

        span.end()

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        with self._lock:
            span = self._node_spans.get((event.run_id, event.node_id))
        if span is None:
            return

        span.set_status(StatusCode.ERROR, event.error)
        span.record_exception(
            Exception(event.error),
            attributes={"exception.stacktrace": event.stacktrace} if event.stacktrace else {},
        )
        # Don't end span here — on_node_complete will do it

    # -- Decision + Tool (lightweight: add events to parent span) --

    async def on_decision_made(self, event: DecisionEvent) -> None:
        span = self._run_spans.get(event.run_id)
        if span is None:
            return

        span.add_event(
            "decision",
            attributes={
                sc.ATTR_DECISION_ID: event.decision_id,
                sc.ATTR_DECISION_INTENT: event.intent,
                sc.ATTR_DECISION_CHOSEN: event.chosen,
                sc.ATTR_DECISION_OPTIONS_COUNT: event.options_count,
            },
        )

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        # Add as event to the node span (or run span if node not found)
        span = self._node_spans.get((event.run_id, event.node_id))
        if span is None:
            span = self._run_spans.get(event.run_id)
        if span is None:
            return

        span.add_event(
            "tool_call",
            attributes={
                sc.ATTR_TOOL_NAME: event.tool_name,
                sc.ATTR_TOOL_IS_ERROR: event.is_error,
                sc.ATTR_TOOL_LATENCY_MS: event.latency_ms,
            },
        )

    # -- Cleanup --

    def shutdown(self) -> None:
        """End all active spans. Call on process shutdown to prevent leaks."""
        with self._lock:
            for span in self._node_spans.values():
                span.set_status(StatusCode.ERROR, "shutdown: span not completed")
                span.end()
            self._node_spans.clear()

            for span in self._run_spans.values():
                span.set_status(StatusCode.ERROR, "shutdown: run not completed")
                span.end()
            self._run_spans.clear()

            for ctx_data in self._run_contexts.values():
                _, token = ctx_data
                otel_context.detach(token)
            self._run_contexts.clear()
