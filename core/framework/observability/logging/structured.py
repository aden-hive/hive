"""Structured logging."""

import logging
import json
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context variables for log correlation
trace_id_ctx: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
span_id_ctx: ContextVar[Optional[str]] = ContextVar('span_id', default=None)
user_id_ctx: ContextVar[Optional[str]] = ContextVar('user_id', default=None)
tenant_id_ctx: ContextVar[Optional[str]] = ContextVar('tenant_id', default=None)


class StructuredLogger:
    """Structured JSON logger."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # JSON formatter
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

    def _build_log_dict(
        self,
        level: str,
        message: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Build structured log dictionary."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "logger": self.logger.name,
            "message": message,
            "trace_id": trace_id_ctx.get(),
            "span_id": span_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "tenant_id": tenant_id_ctx.get(),
            **kwargs
        }

    def info(self, message: str, **kwargs):
        """Log info message."""
        log_dict = self._build_log_dict("INFO", message, **kwargs)
        self.logger.info(json.dumps(log_dict))

    def error(self, message: str, **kwargs):
        """Log error message."""
        log_dict = self._build_log_dict("ERROR", message, **kwargs)
        self.logger.error(json.dumps(log_dict))

    def warning(self, message: str, **kwargs):
        """Log warning message."""
        log_dict = self._build_log_dict("WARNING", message, **kwargs)
        self.logger.warning(json.dumps(log_dict))

    def debug(self, message: str, **kwargs):
        """Log debug message."""
        log_dict = self._build_log_dict("DEBUG", message, **kwargs)
        self.logger.debug(json.dumps(log_dict))


class JSONFormatter(logging.Formatter):
    """JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_dict = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id_ctx.get(),
            "span_id": span_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "tenant_id": tenant_id_ctx.get(),
        }

        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_dict)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)
