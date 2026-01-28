"""
Structured logging with automatic trace context propagation.

Key Features:
- Zero developer friction: Standard logger.info() calls get automatic context
- ContextVar-based propagation: Thread-safe and async-safe
- Dual output modes: JSON for production, human-readable for development
- Correlation IDs: trace_id follows entire request flow automatically

Architecture:
    Runtime.start_run() → Generates trace_id, sets context once
        ↓ (automatic propagation via ContextVar)
    GraphExecutor.execute() → Adds agent_id to context
        ↓ (automatic propagation)
    Node.execute() → Adds node_id to context
        ↓ (automatic propagation)
    User code → logger.info("message") → Gets ALL context automatically!
"""

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable for trace propagation
# ContextVar is thread-safe and async-safe - perfect for concurrent agent execution
trace_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "trace_context", default=None
)


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

        # Build base log entry
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add trace context (trace_id, execution_id, agent_id, etc.) - AUTOMATIC!
        log_entry.update(context)

        # Add custom fields from extra (optional)
        event = getattr(record, "event", None)
        if event is not None:
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

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

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
        trace_id = f"tr_{uuid.uuid4().hex}"  # Full UUID for uniqueness
        set_trace_context(
            trace_id=trace_id,
            execution_id=run_id,
            goal_id=goal_id
        )
        # All subsequent logs in this execution get these fields automatically!
    """
    current = trace_context.get() or {}
    trace_context.set({**current, **kwargs})


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

    Note: Framework typically doesn't need to call this - ContextVar
    is execution-scoped and cleans itself up automatically.
    """
    trace_context.set(None)
