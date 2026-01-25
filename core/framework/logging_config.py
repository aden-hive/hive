"""
Structured Logging Configuration

Production-grade logging with structlog:
- JSON output for log aggregation
- Correlation IDs for request tracing
- Performance metrics in logs
- Async-safe logging
"""

from __future__ import annotations

import contextvars
import logging
import sys
import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

import structlog
from structlog.types import Processor

# Context variables for request tracing
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
agent_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent_id", default="")
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")

T = TypeVar("T")


def add_context_vars(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add context variables to log entries."""
    request_id = request_id_var.get()
    agent_id = agent_id_var.get()
    run_id = run_id_var.get()
    
    if request_id:
        event_dict["request_id"] = request_id
    if agent_id:
        event_dict["agent_id"] = agent_id
    if run_id:
        event_dict["run_id"] = run_id
    
    return event_dict


def add_service_info(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add service information to log entries."""
    event_dict["service"] = "hive-framework"
    event_dict["version"] = "0.2.0"
    return event_dict


def configure_logging(
    json_output: bool = False,
    log_level: str = "INFO",
    include_timestamps: bool = True,
) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        json_output: Output logs as JSON (for production)
        log_level: Minimum log level
        include_timestamps: Include ISO timestamps
    
    Usage:
        # Development (colored console output)
        configure_logging(json_output=False, log_level="DEBUG")
        
        # Production (JSON for log aggregation)
        configure_logging(json_output=True, log_level="INFO")
    """
    # Build processor chain
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_context_vars,
        add_service_info,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if include_timestamps:
        shared_processors.insert(
            0,
            structlog.processors.TimeStamper(fmt="iso", utc=True)
        )
    
    if json_output:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Colored console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        ]
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger.
    
    Usage:
        logger = get_logger(__name__)
        logger.info("Processing request", user_id=123)
    """
    return structlog.get_logger(name)


# =============================================================================
# Context Managers
# =============================================================================

class LogContext:
    """
    Context manager for adding context to logs.
    
    Usage:
        with LogContext(request_id="req-123", agent_id="agent-456"):
            logger.info("Processing")  # Includes request_id and agent_id
    """
    
    def __init__(
        self,
        request_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        self.request_id = request_id
        self.agent_id = agent_id
        self.run_id = run_id
        self._tokens: list = []
    
    def __enter__(self):
        if self.request_id:
            self._tokens.append(request_id_var.set(self.request_id))
        if self.agent_id:
            self._tokens.append(agent_id_var.set(self.agent_id))
        if self.run_id:
            self._tokens.append(run_id_var.set(self.run_id))
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        for token in self._tokens:
            try:
                # Reset context variables
                pass  # contextvars handle cleanup automatically
            except ValueError:
                pass


# =============================================================================
# Performance Logging
# =============================================================================

def log_performance(
    operation: str,
    logger: Optional[structlog.stdlib.BoundLogger] = None,
):
    """
    Decorator to log function performance.
    
    Usage:
        @log_performance("llm_call")
        async def call_llm(prompt):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        _logger = logger or get_logger(func.__module__)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            start = time.perf_counter()
            
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                
                _logger.info(
                    f"{operation} completed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                    success=True,
                )
                
                return result
                
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                
                _logger.error(
                    f"{operation} failed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            start = time.perf_counter()
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                
                _logger.info(
                    f"{operation} completed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                    success=True,
                )
                
                return result
                
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                
                _logger.error(
                    f"{operation} failed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# Agent Execution Logger
# =============================================================================

class AgentExecutionLogger:
    """
    Specialized logger for agent execution events.
    
    Provides structured logging for:
    - Node execution
    - Decision making
    - Tool calls
    - Run lifecycle
    
    Usage:
        exec_logger = AgentExecutionLogger(run_id="run-123", agent_id="agent-456")
        exec_logger.node_started("analyze", {"input": "data"})
        exec_logger.node_completed("analyze", {"output": "result"}, duration_ms=150)
    """
    
    def __init__(
        self,
        run_id: str,
        agent_id: str = "",
        goal_id: str = "",
    ):
        self.run_id = run_id
        self.agent_id = agent_id
        self.goal_id = goal_id
        self.logger = get_logger("agent.execution")
        
        # Set context variables
        run_id_var.set(run_id)
        if agent_id:
            agent_id_var.set(agent_id)
    
    def run_started(self, input_data: dict[str, Any]) -> None:
        """Log run start."""
        self.logger.info(
            "Run started",
            event="run_started",
            run_id=self.run_id,
            agent_id=self.agent_id,
            goal_id=self.goal_id,
            input_keys=list(input_data.keys()),
        )
    
    def run_completed(
        self,
        success: bool,
        output_data: dict[str, Any],
        duration_ms: float,
        tokens_used: int = 0,
    ) -> None:
        """Log run completion."""
        log_func = self.logger.info if success else self.logger.error
        log_func(
            "Run completed",
            event="run_completed",
            run_id=self.run_id,
            success=success,
            duration_ms=round(duration_ms, 2),
            tokens_used=tokens_used,
            output_keys=list(output_data.keys()),
        )
    
    def node_started(
        self,
        node_id: str,
        input_data: dict[str, Any],
    ) -> None:
        """Log node execution start."""
        self.logger.debug(
            "Node started",
            event="node_started",
            node_id=node_id,
            input_keys=list(input_data.keys()),
        )
    
    def node_completed(
        self,
        node_id: str,
        output_data: dict[str, Any],
        duration_ms: float,
        tokens_used: int = 0,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Log node execution completion."""
        log_func = self.logger.info if success else self.logger.warning
        log_func(
            "Node completed",
            event="node_completed",
            node_id=node_id,
            success=success,
            duration_ms=round(duration_ms, 2),
            tokens_used=tokens_used,
            output_keys=list(output_data.keys()),
            error=error,
        )
    
    def decision_made(
        self,
        node_id: str,
        intent: str,
        chosen_option: str,
        reasoning: str,
        options_count: int,
    ) -> None:
        """Log decision making."""
        self.logger.info(
            "Decision made",
            event="decision_made",
            node_id=node_id,
            intent=intent[:100],  # Truncate for log readability
            chosen_option=chosen_option,
            options_count=options_count,
        )
    
    def tool_called(
        self,
        tool_name: str,
        input_params: dict[str, Any],
        duration_ms: float,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Log tool invocation."""
        log_func = self.logger.debug if success else self.logger.warning
        log_func(
            "Tool called",
            event="tool_called",
            tool_name=tool_name,
            success=success,
            duration_ms=round(duration_ms, 2),
            input_keys=list(input_params.keys()),
            error=error,
        )
    
    def hitl_requested(
        self,
        node_id: str,
        questions: list[str],
    ) -> None:
        """Log HITL request."""
        self.logger.info(
            "HITL requested",
            event="hitl_requested",
            node_id=node_id,
            question_count=len(questions),
        )
    
    def hitl_responded(
        self,
        node_id: str,
        response_time_ms: float,
    ) -> None:
        """Log HITL response."""
        self.logger.info(
            "HITL responded",
            event="hitl_responded",
            node_id=node_id,
            response_time_ms=round(response_time_ms, 2),
        )


# =============================================================================
# Initialize Default Configuration
# =============================================================================

def init_logging(
    production: bool = False,
    log_level: str = "INFO",
) -> None:
    """
    Initialize logging with sensible defaults.
    
    Args:
        production: Enable production mode (JSON output)
        log_level: Minimum log level
    """
    configure_logging(
        json_output=production,
        log_level=log_level,
        include_timestamps=True,
    )
