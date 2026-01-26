import asyncio
import time
from typing import SupportsFloat


async def asleep(seconds: SupportsFloat) -> None:
    """
    Equivalent to asyncio.sleep(), converted to time.sleep() by async_to_sync.
    """
    await asyncio.sleep(float(seconds))


def sleep(seconds: SupportsFloat) -> None:
    """
    Equivalent to time.sleep(), converted to asyncio.sleep() by async_to_sync.
    """
    time.sleep(float(seconds))
