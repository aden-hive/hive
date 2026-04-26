"""Async retry utilities with exponential backoff.

This module provides utilities for retrying async operations with configurable
exponential backoff.
"""

import asyncio
from typing import Any


def _calculate_delay(initial_delay: float, max_delay: float, exponential_base: float, attempt: int) -> float:
    """Calculate the delay for a given attempt using exponential backoff."""
    delay = initial_delay * (exponential_base**attempt)
    return min(delay, max_delay)


async def async_retry_operation(
    max_retries: int,
    retry_on: tuple[type[Exception], ...],
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
    operation: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an async operation with retry logic.

    Args:
        max_retries: Maximum number of retry attempts.
        retry_on: Tuple of exception types that should trigger a retry.
        initial_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        exponential_base: Base for exponential backoff calculation.
        operation: The async operation to execute.
        *args: Positional arguments to pass to the operation.
        **kwargs: Keyword arguments to pass to the operation.

    Returns:
        The result of the operation.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await operation(*args, **kwargs)
        except retry_on as e:  # noqa: PERF203
            last_exception = e
            if attempt < max_retries:
                delay = _calculate_delay(initial_delay, max_delay, exponential_base, attempt)
                await asyncio.sleep(delay)
            else:
                # Last attempt failed, re-raise
                raise

    # This should never be reached, but satisfy type checker
    if last_exception:
        raise last_exception
    msg = "Retry operation failed without exception"
    raise RuntimeError(msg)
