"""
Retry utilities with exponential backoff and jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("framework.net.retry")


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """
    Execute an async function with exponential backoff retry.

    Args:
        func: Async callable to retry.
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        jitter: Add random jitter to prevent thundering herd.
        retryable_exceptions: Exception types that trigger a retry.
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.warning(
                    "All %d retries exhausted for %s: %s",
                    max_retries,
                    getattr(func, "__name__", "callable"),
                    e,
                )
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            if jitter:
                delay = delay * (0.5 + random.random() * 0.5)

            logger.info(
                "Retry %d/%d for %s in %.1fs: %s",
                attempt + 1,
                max_retries,
                getattr(func, "__name__", "callable"),
                delay,
                e,
            )
            await asyncio.sleep(delay)

    # Should never reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry loop exited unexpectedly")
