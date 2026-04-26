"""Async wait utilities for testing and polling.

This module provides utilities for waiting on conditions, primarily used
in tests and for polling store readiness.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import SupportsFloat


async def async_wait_for_true(bool_fn: Callable[[], Awaitable[bool]], tries: int = 10, wait_time: SupportsFloat = 1) -> bool:
    """Wait for an async boolean function to return True.

    This is useful for waiting for a store to be ready or for a condition
    to become true.

    Args:
        bool_fn: An async function that returns a boolean.
        tries: Maximum number of attempts.
        wait_time: Time to wait between attempts in seconds.

    Returns:
        True if the function returned True within the allowed attempts,
        False otherwise.
    """
    for _ in range(tries):
        if await bool_fn():
            return True
        await asyncio.sleep(float(wait_time))
    return False
