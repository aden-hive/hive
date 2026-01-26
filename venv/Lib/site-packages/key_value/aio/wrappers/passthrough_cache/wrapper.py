from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper
from key_value.aio.wrappers.ttl_clamp import TTLClampWrapper

DEFAULT_MAX_TTL: float = 30.0 * 60.0
DEFAULT_MISSING_TTL: float = 30.0 * 60.0


class PassthroughCacheWrapper(BaseWrapper):
    """Two-tier wrapper: reads from cache store, falls back to primary and populates cache.

    TTLs from the primary are respected when writing into the cache using a clamped TTL policy.
    """

    def __init__(
        self,
        primary_key_value: AsyncKeyValue,
        cache_key_value: AsyncKeyValue,
        maximum_ttl: SupportsFloat | None = None,
        missing_ttl: SupportsFloat | None = None,
    ) -> None:
        """Initialize the passthrough cache wrapper.

        Args:
            primary_key_value: The primary store to wrap.
            cache_key_value: The cache store to wrap.
            maximum_ttl: The maximum TTL for puts into the cache store. Defaults to 30 minutes.
            missing_ttl: The TTL to use for entries that do not have a TTL. Defaults to 30 minutes.
        """
        self.primary_key_value: AsyncKeyValue = primary_key_value
        self.unwrapped_cache_key_value: AsyncKeyValue = cache_key_value

        self.cache_key_value = TTLClampWrapper(
            key_value=cache_key_value,
            min_ttl=0,
            max_ttl=maximum_ttl or DEFAULT_MAX_TTL,
            missing_ttl=missing_ttl or DEFAULT_MISSING_TTL,
        )

        super().__init__()

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        if managed_entry := await self.cache_key_value.get(collection=collection, key=key):
            return managed_entry

        uncached_entry, ttl = await self.primary_key_value.ttl(collection=collection, key=key)

        if not uncached_entry:
            return None

        await self.cache_key_value.put(collection=collection, key=key, value=uncached_entry, ttl=ttl)

        return uncached_entry

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        key_to_value: dict[str, dict[str, Any] | None] = dict.fromkeys(keys, None)

        # First check the cache store for the entries
        cached_entries: list[dict[str, Any] | None] = await self.cache_key_value.get_many(collection=collection, keys=keys)

        for i, key in enumerate(keys):
            key_to_value[key] = cached_entries[i]

        uncached_keys = [key for key, value in key_to_value.items() if value is None]

        uncached_entries: list[tuple[dict[str, Any] | None, float | None]] = await self.primary_key_value.ttl_many(
            collection=collection, keys=uncached_keys
        )

        # Cache entries individually since they may have different TTLs
        for i, key in enumerate(uncached_keys):
            entry, ttl = uncached_entries[i]
            if entry is not None:
                await self.cache_key_value.put(collection=collection, key=key, value=entry, ttl=ttl)

            key_to_value[key] = entry

        return [key_to_value[key] for key in keys]

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        cached_entry, ttl = await self.cache_key_value.ttl(collection=collection, key=key)

        if cached_entry:
            return cached_entry, ttl

        uncached_entry, ttl = await self.primary_key_value.ttl(collection=collection, key=key)

        if not uncached_entry:
            return (None, None)

        await self.cache_key_value.put(collection=collection, key=key, value=uncached_entry, ttl=ttl)

        return uncached_entry, ttl

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        key_to_value: dict[str, tuple[dict[str, Any] | None, float | None]] = dict.fromkeys(keys, (None, None))  # type: ignore

        # First check the cache store for the entries
        cached_entries: list[tuple[dict[str, Any] | None, float | None]] = await self.cache_key_value.ttl_many(
            collection=collection, keys=keys
        )

        for i, key in enumerate(keys):
            key_to_value[key] = (cached_entries[i][0], cached_entries[i][1])

        uncached_keys = [key for key, value in key_to_value.items() if value == (None, None)]

        uncached_entries: list[tuple[dict[str, Any] | None, float | None]] = await self.primary_key_value.ttl_many(
            collection=collection, keys=uncached_keys
        )

        # Cache entries individually since they may have different TTLs
        for i, key in enumerate(uncached_keys):
            entry, ttl = uncached_entries[i]
            if entry is not None:
                await self.cache_key_value.put(collection=collection, key=key, value=entry, ttl=ttl)

            key_to_value[key] = (entry, ttl)

        return [key_to_value[key] for key in keys]

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        _ = await self.cache_key_value.delete(collection=collection, key=key)

        await self.primary_key_value.put(collection=collection, key=key, value=value, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        _ = await self.cache_key_value.delete_many(collection=collection, keys=keys)

        await self.primary_key_value.put_many(keys=keys, values=values, collection=collection, ttl=ttl)

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        _ = await self.cache_key_value.delete(collection=collection, key=key)

        return await self.primary_key_value.delete(collection=collection, key=key)

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        _ = await self.cache_key_value.delete_many(collection=collection, keys=keys)

        return await self.primary_key_value.delete_many(collection=collection, keys=keys)
