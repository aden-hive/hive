from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.constants import DEFAULT_COLLECTION_NAME
from key_value.shared.utils.compound import prefix_collection, unprefix_collection
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class PrefixCollectionsWrapper(BaseWrapper):
    """A wrapper that prefixes collection names before delegating to the underlying store."""

    def __init__(self, key_value: AsyncKeyValue, prefix: str, default_collection: str | None = None) -> None:
        """Initialize the prefix collections wrapper.

        Args:
            key_value: The store to wrap.
            prefix: The prefix to add to the collections.
            default_collection: The default collection to use if no collection is provided. Will be automatically prefixed with the `prefix`
        """
        self.key_value: AsyncKeyValue = key_value
        self.prefix: str = prefix
        self.default_collection: str = default_collection or DEFAULT_COLLECTION_NAME
        super().__init__()

    def _prefix_collection(self, collection: str | None) -> str:
        return prefix_collection(prefix=self.prefix, collection=collection or self.default_collection)

    def _unprefix_collection(self, collection: str) -> str:
        return unprefix_collection(prefix=self.prefix, collection=collection)

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.get(key=key, collection=new_collection)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.get_many(keys=keys, collection=new_collection)

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.ttl(key=key, collection=new_collection)

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.ttl_many(keys=keys, collection=new_collection)

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.put(key=key, value=value, collection=new_collection, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.put_many(keys=keys, values=values, collection=new_collection, ttl=ttl)

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.delete(key=key, collection=new_collection)

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        new_collection: str = self._prefix_collection(collection=collection)
        return await self.key_value.delete_many(keys=keys, collection=new_collection)
