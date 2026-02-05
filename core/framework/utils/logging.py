import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

class JsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings suitable for log aggregation systems
    (Datadog, CloudWatch, ELK, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        # 1. Base log record data
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "line": record.lineno,
        }

        # 2. Add extra fields passed via extra={...}
        # Filter out standard LogRecord attributes so we only get the 'extra' ones
        standard_attributes = {
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module',
            'msecs', 'message', 'msg', 'name', 'pathname', 'process',
            'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName'
        }

        for key, value in record.__dict__.items():
            if key not in standard_attributes and not key.startswith("_"):
                try:
                    json.dumps(value)  # Simple check if serializable
                    log_record[key] = value
                except (TypeError, OverflowError):
                    log_record[key] = str(value)

        # 3. Handle Exceptions
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)

def setup_logging(name: str = "hive", level: str = "INFO") -> logging.Logger:
    """
    Configures the logger based on environment variables.
    
    Env Vars:
        HIV_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
        HIV_LOG_FORMAT: text, json (default: text)
    """
    # Get config from env or defaults
    log_level_str = os.getenv("HIV_LOG_LEVEL", level).upper()
    log_format = os.getenv("HIV_LOG_FORMAT", "text").lower()
    
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Avoid adding duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if log_format == "json":
        formatter = JsonFormatter()
    else:
        # Standard human-readable format
        formatter = logging.Formatter(
            fmt="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger