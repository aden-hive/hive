"""Structured logging configuration for Hive framework.

Provides consistent, structured logging across all framework components.
Supports both development (human-readable) and production (JSON) modes.

Usage:
    from framework.logging import get_logger, configure_logging

    # Configure at startup
    configure_logging(
        level="DEBUG",
        json_format=False,  # True for production
    )

    # In modules
    logger = get_logger(__name__)
    logger.info("Processing node", node_id="abc123", status="running")
"""

import json
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class LogLevel(StrEnum):
    """Log levels matching Python's logging module."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogConfig:
    """Logging configuration options."""

    level: LogLevel = LogLevel.INFO
    json_format: bool = False
    include_timestamp: bool = True
    include_caller: bool = True
    log_file: str | None = None


class StructuredFormatter(logging.Formatter):
    """Formatter that outputs structured JSON logs for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add caller info
        log_data["caller"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Add extra fields (structured data)
        extra_keys = set(record.__dict__.keys()) - {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }
        for key in extra_keys:
            value = getattr(record, key)
            if isinstance(value, (str, int, float, bool, type(None))):
                log_data[key] = value
            elif isinstance(value, Mapping):
                log_data[key] = dict(value)
            else:
                log_data[key] = str(value)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class PrettyFormatter(logging.Formatter):
    """Formatter that outputs human-readable logs for development."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Level with optional color
        level = record.levelname
        if self.use_colors:
            color = self.COLORS.get(level, "")
            level_str = f"{color}{level:8}{self.RESET}"
        else:
            level_str = f"{level:8}"

        # Logger name (shortened)
        logger_name = record.name
        if len(logger_name) > 25:
            parts = logger_name.split(".")
            if len(parts) > 2:
                logger_name = f"{parts[0]}...{parts[-1]}"

        # Main message
        message = record.getMessage()

        # Build base log line
        base = f"{self.DIM}{timestamp}{self.RESET} {level_str} {self.BOLD}{logger_name}{self.RESET} │ {message}"

        # Add extra fields
        extra_keys = set(record.__dict__.keys()) - {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }

        if extra_keys:
            extras = []
            for key in sorted(extra_keys):
                value = getattr(record, key)
                if self.use_colors:
                    extras.append(f"{self.DIM}{key}={self.RESET}{value}")
                else:
                    extras.append(f"{key}={value}")
            base += f" │ {' '.join(extras)}"

        # Add exception if present
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"

        return base


class StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that supports structured key-value logging."""

    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        # Move all extra kwargs to the 'extra' dict
        extra = kwargs.get("extra", {})
        for key in list(kwargs.keys()):
            if key not in ("exc_info", "stack_info", "stacklevel", "extra"):
                extra[key] = kwargs.pop(key)
        kwargs["extra"] = extra
        return msg, kwargs


# Global configuration
_config: LogConfig = LogConfig()
_configured: bool = False


def configure_logging(
    level: str | LogLevel = LogLevel.INFO,
    json_format: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure logging for the entire framework.

    Should be called once at application startup.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, output JSON logs (for production)
        log_file: Optional file path to also write logs to
    """
    global _config, _configured

    if isinstance(level, str):
        level = LogLevel(level.upper())

    _config = LogConfig(
        level=level,
        json_format=json_format,
        log_file=log_file,
    )

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(_config.level.value)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if _config.json_format:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(PrettyFormatter())
    root.addHandler(console_handler)

    # File handler (if specified)
    if _config.log_file:
        file_handler = logging.FileHandler(_config.log_file)
        file_handler.setFormatter(StructuredFormatter())  # Always JSON for files
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for the given module name.

    Args:
        name: Module name, typically __name__

    Returns:
        StructuredLogger that supports key-value logging

    Example:
        logger = get_logger(__name__)
        logger.info("Processing started", node_id="abc", step=1)
    """
    if not _configured:
        # Auto-configure with defaults if not already done
        configure_logging()

    base_logger = logging.getLogger(name)
    return StructuredLogger(base_logger, {})


# Convenience function to get framework root logger
def get_framework_logger() -> StructuredLogger:
    """Get the root framework logger."""
    return get_logger("framework")


__all__ = [
    "configure_logging",
    "get_logger",
    "get_framework_logger",
    "LogLevel",
    "LogConfig",
    "StructuredLogger",
]
