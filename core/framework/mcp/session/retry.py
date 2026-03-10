"""Retry helpers for MCP session runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_once(
    operation: Callable[[], T],
    should_retry: Callable[[Exception], bool],
    before_retry: Callable[[], None] | None = None,
) -> T:
    """Execute operation and retry once when should_retry returns True."""
    try:
        return operation()
    except Exception as exc:
        if not should_retry(exc):
            raise
        if before_retry is not None:
            before_retry()
        return operation()
