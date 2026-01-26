import asyncio
from collections.abc import Awaitable
from typing import Any


async def async_gather(*aws: Awaitable[Any], return_exceptions: bool = False) -> list[Any]:
    """
    Equivalent to asyncio.gather(), converted to asyncio.gather() by async_to_sync.
    """
    return await asyncio.gather(*aws, return_exceptions=return_exceptions)


def gather(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
    """
    Equivalent to asyncio.gather(), converted to asyncio.gather() by async_to_sync.
    """
    return args
