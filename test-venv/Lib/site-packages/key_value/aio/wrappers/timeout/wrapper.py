import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class TimeoutWrapper(BaseWrapper):
    """Wrapper that adds timeout limits to all operations.

    This wrapper ensures that no operation takes longer than the specified timeout.
    If an operation exceeds the timeout, it raises asyncio.TimeoutError. This is useful
    for preventing operations from hanging indefinitely and for enforcing SLAs.
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the timeout wrapper.

        Args:
            key_value: The store to wrap.
            timeout: Timeout in seconds for all operations. Defaults to 5.0 seconds.
        """
        self.key_value: AsyncKeyValue = key_value
        self.timeout: float = timeout

        super().__init__()

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        return await asyncio.wait_for(self.key_value.get(key=key, collection=collection), timeout=self.timeout)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        return await asyncio.wait_for(self.key_value.get_many(keys=keys, collection=collection), timeout=self.timeout)

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        return await asyncio.wait_for(self.key_value.ttl(key=key, collection=collection), timeout=self.timeout)

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        return await asyncio.wait_for(self.key_value.ttl_many(keys=keys, collection=collection), timeout=self.timeout)

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        return await asyncio.wait_for(self.key_value.put(key=key, value=value, collection=collection, ttl=ttl), timeout=self.timeout)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        return await asyncio.wait_for(
            self.key_value.put_many(keys=keys, values=values, collection=collection, ttl=ttl), timeout=self.timeout
        )

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        return await asyncio.wait_for(self.key_value.delete(key=key, collection=collection), timeout=self.timeout)

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        return await asyncio.wait_for(self.key_value.delete_many(keys=keys, collection=collection), timeout=self.timeout)
