"""
Browser telemetry logging - rich context for debugging browser tools.

Logs are written to .hive/browser-logs/ as JSON lines for easy parsing.
Each log entry includes:
- Timestamp and unique trace ID
- Agent/profile context
- Tool/operation name and parameters
- Timing information
- Results or errors with full context
"""

from __future__ import annotations

import functools
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

# Try to import context variable, but don't fail if not available
try:
    from .session import _active_profile
except ImportError:
    _active_profile = None

# Type variables for decorator
F = TypeVar("F", bound=Callable[..., Any])

# Log directory setup
LOG_DIR = Path(__file__).parent.parent.parent.parent.parent / ".hive" / "browser-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Current log file (rotated daily)
_current_log_file: Path | None = None
_log_file_date: str | None = None


def _get_log_file() -> Path:
    """Get the current log file, rotating daily."""
    global _current_log_file, _log_file_date

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _log_file_date != today:
        _log_file_date = today
        _current_log_file = LOG_DIR / f"browser-{today}.jsonl"

    return _current_log_file


def _get_profile() -> str:
    """Get the current profile from context variable."""
    if _active_profile is not None:
        try:
            return _active_profile.get()
        except Exception:
            pass
    return "default"


def _truncate(value: Any, max_len: int = 500) -> Any:
    """Truncate long strings for readability."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"... (+{len(value) - max_len} chars)"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 10:
            return [_truncate(v, max_len) for v in value[:10]] + [f"... (+{len(value) - 10} items)"]
        return [_truncate(v, max_len) for v in value]
    return value


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Sanitize parameters for logging - remove sensitive data, truncate."""
    sanitized = {}
    sensitive_keys = {"password", "token", "secret", "credential", "api_key", "apikey"}

    for key, value in params.items():
        key_lower = key.lower()
        if any(s in key_lower for s in sensitive_keys):
            sanitized[key] = "***REDACTED***"
        else:
            sanitized[key] = _truncate(value)

    return sanitized


def write_log(entry: dict[str, Any]) -> None:
    """Write a log entry to the current log file."""
    try:
        log_file = _get_log_file()
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        entry["profile"] = _get_profile()

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Don't let logging errors break operations
        pass


def log_tool_call(
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: Exception | None = None,
    duration_ms: float | None = None,
) -> None:
    """Log a tool invocation."""
    entry: dict[str, Any] = {
        "type": "tool_call",
        "tool": tool_name,
        "params": _sanitize_params(params),
    }

    if result is not None:
        entry["result"] = _truncate(result, max_len=1000)
        entry["ok"] = result.get("ok", True)

    if error is not None:
        entry["error"] = str(error)
        entry["error_type"] = type(error).__name__
        entry["traceback"] = traceback.format_exc()

    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)

    write_log(entry)


def log_bridge_message(
    direction: str,  # "send" or "recv"
    msg_type: str,
    msg_id: str | int | None = None,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Log a bridge WebSocket message."""
    entry: dict[str, Any] = {
        "type": "bridge",
        "direction": direction,
        "msg_type": msg_type,
    }

    if msg_id is not None:
        entry["msg_id"] = msg_id

    if params:
        entry["params"] = _sanitize_params(params)

    if result:
        entry["result"] = _truncate(result, max_len=1000)

    if error:
        entry["error"] = error

    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)

    write_log(entry)


def log_context_event(
    event: str,  # "create", "destroy", "start", "stop"
    profile: str,
    group_id: int | None = None,
    tab_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log a browser context lifecycle event."""
    entry: dict[str, Any] = {
        "type": "context",
        "event": event,
        "profile": profile,
    }

    if group_id is not None:
        entry["group_id"] = group_id

    if tab_id is not None:
        entry["tab_id"] = tab_id

    if details:
        entry["details"] = _truncate(details)

    write_log(entry)


def log_cdp_command(
    tab_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Log a CDP command."""
    entry: dict[str, Any] = {
        "type": "cdp",
        "tab_id": tab_id,
        "method": method,
    }

    if params:
        entry["params"] = _sanitize_params(params)

    if result:
        # CDP results can be large, truncate aggressively
        entry["result"] = _truncate(result, max_len=300)

    if error:
        entry["error"] = error

    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)

    write_log(entry)


def log_connection_event(
    event: str,  # "connect", "disconnect", "hello"
    details: dict[str, Any] | None = None,
) -> None:
    """Log a connection event."""
    entry: dict[str, Any] = {
        "type": "connection",
        "event": event,
    }

    if details:
        entry["details"] = _truncate(details)

    write_log(entry)


# Decorator for instrumenting tool functions
def instrument_tool(tool_name: str) -> Callable[[F], F]:
    """Decorator to log tool calls with timing and error handling."""

    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_tool_call(tool_name, kwargs, result=result, duration_ms=duration_ms)
                    return result
                except Exception as e:
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_tool_call(tool_name, kwargs, error=e, duration_ms=duration_ms)
                    raise

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_tool_call(tool_name, kwargs, result=result, duration_ms=duration_ms)
                    return result
                except Exception as e:
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_tool_call(tool_name, kwargs, error=e, duration_ms=duration_ms)
                    raise

            return sync_wrapper  # type: ignore

    return decorator


# Import asyncio at the end to avoid circular import issues
import asyncio
