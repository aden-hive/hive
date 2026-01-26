from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.utils.compound import prefix_key, unprefix_key
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class PrefixKeysWrapper(BaseWrapper):
    """A wrapper that prefixes key names before delegating to the underlying store."""

    def __init__(self, key_value: AsyncKeyValue, prefix: str) -> None:
        """Initialize the prefix keys wrapper.

        Args:
            key_value: The store to wrap.
            prefix: The prefix to add to the keys.
        """
        self.key_value: AsyncKeyValue = key_value
        self.prefix: str = prefix
        super().__init__()

    def _prefix_key(self, key: str) -> str:
        return prefix_key(prefix=self.prefix, key=key)

    def _unprefix_key(self, key: str) -> str:
        return unprefix_key(prefix=self.prefix, key=key)

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        new_key: str = self._prefix_key(key=key)
        return await self.key_value.get(key=new_key, collection=collection)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        new_keys: Sequence[str] = [self._prefix_key(key=key) for key in keys]
        return await self.key_value.get_many(keys=new_keys, collection=collection)

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        new_key: str = self._prefix_key(key=key)
        return await self.key_value.ttl(key=new_key, collection=collection)

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        new_keys: Sequence[str] = [self._prefix_key(key=key) for key in keys]
        return await self.key_value.ttl_many(keys=new_keys, collection=collection)

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        new_key: str = self._prefix_key(key=key)
        return await self.key_value.put(key=new_key, value=value, collection=collection, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        new_keys: Sequence[str] = [self._prefix_key(key=key) for key in keys]
        return await self.key_value.put_many(keys=new_keys, values=values, collection=collection, ttl=ttl)

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        new_key: str = self._prefix_key(key=key)
        return await self.key_value.delete(key=new_key, collection=collection)

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        new_keys: Sequence[str] = [self._prefix_key(key=key) for key in keys]
        return await self.key_value.delete_many(keys=new_keys, collection=collection)
