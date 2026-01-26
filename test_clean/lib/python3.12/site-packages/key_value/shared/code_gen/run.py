from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

from key_value.shared.code_gen.sleep import asleep, sleep


async def await_awaitable(awaitable: Awaitable[Any]) -> Any:
    """
    Equivalent to await awaitable, converted to await awaitable by async_to_sync.
    """
    return await awaitable


def run_function(function: Callable[..., Any]) -> Any:
    """
    Equivalent to function(), converted to function() by async_to_sync.
    """
    return function()


def _calculate_delay(initial_delay: float, max_delay: float, exponential_base: float, attempt: int) -> float:
    """Calculate the delay for a given attempt using exponential backoff."""
    delay = initial_delay * (exponential_base**attempt)
    return min(delay, max_delay)


T = TypeVar("T")


async def async_retry_operation(
    max_retries: int,
    retry_on: tuple[type[Exception], ...],
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
    operation: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute an operation with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await operation(*args, **kwargs)
        except retry_on as e:  # noqa: PERF203
            last_exception = e
            if attempt < max_retries:
                delay = _calculate_delay(initial_delay, max_delay, exponential_base, attempt)
                await asleep(delay)
            else:
                # Last attempt failed, re-raise
                raise

    # This should never be reached, but satisfy type checker
    if last_exception:
        raise last_exception
    msg = "Retry operation failed without exception"
    raise RuntimeError(msg)


def retry_operation(
    max_retries: int,
    retry_on: tuple[type[Exception], ...],
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
    operation: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute an operation with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return operation(*args, **kwargs)
        except retry_on as e:  # noqa: PERF203
            last_exception = e
            if attempt < max_retries:
                delay = _calculate_delay(initial_delay, max_delay, exponential_base, attempt)
                sleep(delay)
            else:
                # Last attempt failed, re-raise
                raise

    # This should never be reached, but satisfy type checker
    if last_exception:
        raise last_exception
    msg = "Retry operation failed without exception"
    raise RuntimeError(msg)
