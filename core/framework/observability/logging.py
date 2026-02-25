"""
Structured logging with automatic trace context propagation.

Key Features:
- Zero developer friction: Standard logger.info() calls get automatic context
- ContextVar-based propagation: Thread-safe and async-safe
- Dual output modes: JSON for production, human-readable for development
- Correlation IDs: trace_id follows entire request flow automatically
- Optional Langfuse observability via OTEL (configure_langfuse())

Architecture:
    Runtime.start_run() → Generates trace_id, sets context once
        ↓ (automatic propagation via ContextVar)
    GraphExecutor.execute() → Adds agent_id to context
        ↓ (automatic propagation)
    Node.execute() → Adds node_id to context
        ↓ (automatic propagation)
    User code → logger.info("message") → Gets ALL context automatically!

Langfuse (optional):
    configure_langfuse() → OTel SDK → Langfuse OTLP endpoint
    set_trace_context(trace_id=...) → opens OTel span (hive trace_id preserved);
                                      closes any prior span in the same context
    atexit handler                  → ends remaining open spans, calls
                                      tracer_provider.shutdown() which does a
                                      blocking force_flush before process exit
"""

import atexit
import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable for trace propagation
# ContextVar is thread-safe and async-safe - perfect for concurrent agent execution
trace_context: ContextVar[dict[str, Any] | None] = ContextVar("trace_context", default=None)

# ANSI escape code pattern (matches \033[...m or \x1b[...m)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m|\033\[[0-9;]*m")


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text for clean JSON logging."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Produces machine-parseable log entries with:
    - Standard fields (timestamp, level, logger, message)
    - Trace context (trace_id, execution_id, agent_id, etc.) - AUTOMATIC
    - Custom fields from extra dict
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Get trace context for correlation - AUTOMATIC!
        context = trace_context.get() or {}

        # Strip ANSI codes from message for clean JSON output
        message = strip_ansi_codes(record.getMessage())

        # Build base log entry
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": message,
        }

        # Add trace context (trace_id, execution_id, agent_id, etc.) - AUTOMATIC!
        log_entry.update(context)

        # Add custom fields from extra (optional)
        event = getattr(record, "event", None)
        if event is not None:
            if isinstance(event, str):
                log_entry["event"] = strip_ansi_codes(str(event))
            else:
                log_entry["event"] = event

        latency_ms = getattr(record, "latency_ms", None)
        if latency_ms is not None:
            log_entry["latency_ms"] = latency_ms

        tokens_used = getattr(record, "tokens_used", None)
        if tokens_used is not None:
            log_entry["tokens_used"] = tokens_used

        node_id = getattr(record, "node_id", None)
        if node_id is not None:
            log_entry["node_id"] = node_id

        model = getattr(record, "model", None)
        if model is not None:
            log_entry["model"] = model

        # Add exception info if present (strip ANSI codes from exception text too)
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            log_entry["exception"] = strip_ansi_codes(exception_text)

        return json.dumps(log_entry)


class HumanReadableFormatter(logging.Formatter):
    """
    Human-readable formatter for development.

    Provides colorized logs with trace context for local debugging.
    Includes trace_id prefix for correlation - AUTOMATIC!
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as human-readable string."""
        # Get trace context - AUTOMATIC!
        context = trace_context.get() or {}
        trace_id = context.get("trace_id", "")
        execution_id = context.get("execution_id", "")
        agent_id = context.get("agent_id", "")

        # Build context prefix
        prefix_parts = []
        if trace_id:
            prefix_parts.append(f"trace:{trace_id[:8]}")
        if execution_id:
            prefix_parts.append(f"exec:{execution_id[-8:]}")
        if agent_id:
            prefix_parts.append(f"agent:{agent_id}")

        context_prefix = f"[{' | '.join(prefix_parts)}] " if prefix_parts else ""

        # Get color
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        # Format log level (5 chars wide for alignment)
        level = f"{record.levelname:<8}"

        # Add event if present
        event = ""
        record_event = getattr(record, "event", None)
        if record_event is not None:
            event = f" [{record_event}]"

        # Format message: [LEVEL] [trace context] message
        return f"{color}[{level}]{reset} {context_prefix}{record.getMessage()}{event}"


def configure_logging(
    level: str = "INFO",
    format: str = "auto",  # "json", "human", or "auto"
) -> None:
    """
    Configure structured logging for the application.

    This should be called ONCE at application startup, typically in:
    - AgentRunner._setup()
    - Main entry point
    - Test fixtures

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format: Output format:
            - "json": Machine-parseable JSON (for production)
            - "human": Human-readable with colors (for development)
            - "auto": JSON if LOG_FORMAT=json or ENV=production, else human

    Examples:
        # Development mode (human-readable)
        configure_logging(level="DEBUG", format="human")

        # Production mode (JSON)
        configure_logging(level="INFO", format="json")

        # Auto-detect from environment
        configure_logging(level="INFO", format="auto")
    """
    # Auto-detect format
    if format == "auto":
        # Use JSON if LOG_FORMAT=json or ENV=production
        log_format_env = os.getenv("LOG_FORMAT", "").lower()
        env = os.getenv("ENV", "development").lower()

        if log_format_env == "json" or env == "production":
            format = "json"
        else:
            format = "human"

    # Select formatter
    if format == "json":
        formatter = StructuredFormatter()
        # Disable colors in third-party libraries when using JSON format
        _disable_third_party_colors()
    else:
        formatter = HumanReadableFormatter()

    # Configure handler
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())

    # When in JSON mode, configure known third-party loggers to use JSON formatter
    # This ensures libraries like LiteLLM, httpcore also output clean JSON
    if format == "json":
        third_party_loggers = [
            "LiteLLM",
            "httpcore",
            "httpx",
            "openai",
        ]
        for logger_name in third_party_loggers:
            logger = logging.getLogger(logger_name)
            # Clear existing handlers so records propagate to root and use our formatter there
            logger.handlers.clear()
            logger.propagate = True  # Still propagate to root for consistency


def _disable_third_party_colors() -> None:
    """Disable color output in third-party libraries for clean JSON logging."""
    # Set NO_COLOR environment variable (common convention for disabling colors)
    os.environ["NO_COLOR"] = "1"
    os.environ["FORCE_COLOR"] = "0"

    # Disable LiteLLM debug/verbose output colors if available
    try:
        import litellm

        # LiteLLM respects NO_COLOR, but we can also suppress debug info
        if hasattr(litellm, "suppress_debug_info"):
            litellm.suppress_debug_info = True  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        pass


# ─── Langfuse / OTel integration ─────────────────────────────────────────────
# Populated only when configure_langfuse() has been called; None otherwise.
# Keyed by trace_id_hex so concurrent runs each have their own span.
_otel_tracer: Any = None
_otel_span_stack: dict[str, tuple[Any, Any]] = {}  # trace_id_hex → (span, ctx_token)


def configure_langfuse(
    public_key: str | None = None,
    secret_key: str | None = None,
    host: str = "https://cloud.langfuse.com",
) -> None:
    """
    Enable Langfuse observability via the OpenTelemetry standard.

    Routes every hive agent run to Langfuse as an OTel trace, with all
    Python log records attached as log events — without touching any runtime
    script.  Call once at application startup alongside configure_logging().

    Credentials are resolved in priority order:
      1. Arguments passed to this function
      2. ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` environment variables

    Args:
        public_key: Langfuse project public key  (starts with ``pk-lf-``).
        secret_key: Langfuse project secret key  (starts with ``sk-lf-``).
        host:       Langfuse host URL.  Defaults to ``https://cloud.langfuse.com``.
                    Override for self-hosted deployments, e.g. ``http://localhost:3000``.

    Requires (optional dependency group)::

        pip install 'framework[langfuse]'
        # installs opentelemetry-sdk + opentelemetry-exporter-otlp-proto-http

    Example::

        configure_logging(level="INFO")
        configure_langfuse()   # reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY from env
    """
    global _otel_tracer

    try:
        import base64

        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger(__name__).warning(
            "Langfuse integration requires opentelemetry-sdk and "
            "opentelemetry-exporter-otlp-proto-http. "
            "Install with: pip install 'framework[langfuse]'"
        )
        return

    pub = public_key or os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sec = secret_key or os.getenv("LANGFUSE_SECRET_KEY", "")
    if not pub or not sec:
        logging.getLogger(__name__).warning(
            "Langfuse integration is disabled: "
            "set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "(or pass public_key/secret_key to configure_langfuse)."
        )
        return

    auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    base = host.rstrip("/")

    # ── Trace exporter → Langfuse OTLP endpoint ──────────────────────────────
    span_exporter = OTLPSpanExporter(
        endpoint=f"{base}/api/public/otel/v1/traces",
        headers=headers,
    )
    resource = Resource.create({"service.name": "hive"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    otel_trace.set_tracer_provider(tracer_provider)
    _otel_tracer = tracer_provider.get_tracer("hive.framework")

    # ── Log bridge: Python logging → OTel logs → Langfuse ────────────────────
    # The OTel logs SDK is still experimental; wrap in try/except so traces
    # still flow even if the log bridge isn't available.
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler as OTelLoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        log_exporter = OTLPLogExporter(
            endpoint=f"{base}/api/public/otel/v1/logs",
            headers=headers,
        )
        log_provider = LoggerProvider(resource=resource)
        log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        set_logger_provider(log_provider)
        logging.getLogger().addHandler(OTelLoggingHandler(logger_provider=log_provider))
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "OTel log bridge unavailable — log events will not appear in Langfuse "
            "(traces still flow): %s",
            exc,
        )

    # ── Process-exit flush ───────────────────────────────────────────────────
    # BatchSpanProcessor.shutdown() does a blocking force_flush, draining the
    # export queue before the process exits.  This is the idiomatic OTel pattern
    # for scripts; no runtime script needs to call clear_trace_context().
    atexit.register(_langfuse_shutdown)

    logging.getLogger(__name__).info(
        "Langfuse OTEL integration enabled",
        extra={"langfuse_host": base},
    )


def _langfuse_shutdown() -> None:
    """
    End all open OTel spans and flush to Langfuse at process exit.

    Registered automatically by configure_langfuse() via atexit.
    Calls tracer_provider.shutdown(), which performs a blocking force_flush
    on the BatchSpanProcessor, draining the export queue before the process
    terminates.
    """
    for trace_id_hex in list(_otel_span_stack):
        _otel_close_trace(trace_id_hex)

    from opentelemetry import trace as otel_trace

    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        try:
            provider.shutdown()
        except Exception as exc:
            logging.getLogger(__name__).debug("Langfuse shutdown error: %s", exc)


def _otel_open_trace(trace_id_hex: str, goal_id: str = "") -> None:
    """
    Open an OTel recording span anchored to *our* trace_id.

    A NonRecordingSpan carrying our trace_id acts as a virtual remote parent.
    The real recording child span inherits that trace_id, so Langfuse shows
    the exact same ID that hive uses internally — no runtime changes required.
    """
    if trace_id_hex in _otel_span_stack:
        return  # already open for this trace

    from opentelemetry import context as otel_ctx, trace as otel_trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    # Virtual remote parent — carries our trace_id, never exported.
    virtual_parent = NonRecordingSpan(
        SpanContext(
            trace_id=int(trace_id_hex, 16),
            span_id=int(os.urandom(8).hex(), 16),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
    )
    parent_ctx = otel_trace.set_span_in_context(virtual_parent)

    # Real recording span — inherits trace_id from virtual parent above.
    span = _otel_tracer.start_span(
        goal_id or "agent.run",
        context=parent_ctx,
        attributes={"hive.trace_id": trace_id_hex},
    )
    token = otel_ctx.attach(otel_trace.set_span_in_context(span))
    _otel_span_stack[trace_id_hex] = (span, token)


def _otel_enrich_span(attrs: dict[str, Any]) -> None:
    """
    Add new context fields as attributes on the span for the current hive trace.

    Uses the trace_id from the hive ContextVar to look up the span directly in
    _otel_span_stack instead of relying on OTel's thread-local get_current_span(),
    which is unsafe under concurrent async execution (StreamRuntime).
    """
    ctx = trace_context.get() or {}
    trace_id = ctx.get("trace_id")
    if not trace_id:
        return
    entry = _otel_span_stack.get(trace_id)
    if entry is None:
        return
    span, _ = entry
    if span.is_recording():
        for k, v in attrs.items():
            if isinstance(v, (str, bool, int, float)):
                span.set_attribute(f"hive.{k}", v)


def _otel_close_trace(trace_id_hex: str) -> None:
    """End the OTel span and detach its context, flushing to Langfuse."""
    from opentelemetry import context as otel_ctx

    entry = _otel_span_stack.pop(trace_id_hex, None)
    if entry is None:
        return
    span, token = entry
    span.end()
    otel_ctx.detach(token)


# ─── Trace context helpers ────────────────────────────────────────────────────


def set_trace_context(**kwargs: Any) -> None:
    """
    Set trace context for current execution.

    Context is stored in a ContextVar and AUTOMATICALLY propagates
    through async calls within the same execution context.

    This is called by the framework at key points:
    - Runtime.start_run(): Sets trace_id, execution_id, goal_id
    - GraphExecutor.execute(): Adds agent_id
    - Node execution: Adds node_id

    Developers/agents NEVER call this directly - it's framework-managed.

    Args:
        **kwargs: Context fields (trace_id, execution_id, agent_id, etc.)

    Example (framework code):
        # In Runtime.start_run()
        trace_id = uuid.uuid4().hex  # 32 hex, W3C Trace Context compliant
        execution_id = uuid.uuid4().hex  # 32 hex, OTel-aligned for correlation
        set_trace_context(
            trace_id=trace_id,
            execution_id=execution_id,
            goal_id=goal_id
        )
        # All subsequent logs in this execution get these fields automatically!
    """
    current = trace_context.get() or {}
    trace_context.set({**current, **kwargs})

    if _otel_tracer is not None:
        if "trace_id" in kwargs:
            # Close the previous span if a different trace_id is replacing it in
            # this context (sequential run pattern: run A ends, run B starts).
            prev_trace_id = current.get("trace_id")
            if prev_trace_id and prev_trace_id != kwargs["trace_id"]:
                _otel_close_trace(prev_trace_id)
            # Open a new OTel span for this trace.
            _otel_open_trace(kwargs["trace_id"], kwargs.get("goal_id", ""))
        else:
            # Subsequent calls (e.g. agent_id added by executor) — enrich span.
            _otel_enrich_span(kwargs)


def get_trace_context() -> dict:
    """
    Get current trace context.

    Returns:
        Dict with trace_id, execution_id, agent_id, etc.
        Empty dict if no context set.
    """
    context = trace_context.get() or {}
    return context.copy()


def clear_trace_context() -> None:
    """
    Clear trace context.

    Useful for:
    - Cleanup between test runs
    - Starting a completely new execution context
    - Manual context management (rare)

    Note: Framework code does not need to call this — ContextVar is
    execution-scoped and cleans itself up automatically.  When Langfuse is
    enabled, open spans are closed at process exit by the atexit handler
    registered in configure_langfuse(); calling clear_trace_context()
    earlier (e.g. in tests) will also close them eagerly.
    """
    ctx = trace_context.get() or {}
    trace_id = ctx.get("trace_id")
    trace_context.set(None)
    if _otel_tracer is not None and trace_id:
        _otel_close_trace(trace_id)
