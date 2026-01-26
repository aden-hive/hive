from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, SupportsFloat

from key_value.shared.constants import DEFAULT_COLLECTION_NAME
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


@dataclass
class BaseStatistics:
    """Base statistics container with operation counting."""

    count: int = field(default=0)
    """The number of operations."""

    def increment(self, *, increment: int = 1) -> None:
        self.count += increment


@dataclass
class BaseHitMissStatistics(BaseStatistics):
    """Statistics container with hit/miss tracking for cache-like operations."""

    hit: int = field(default=0)
    """The number of hits."""
    miss: int = field(default=0)
    """The number of misses."""

    def increment_hit(self, *, increment: int = 1) -> None:
        self.increment(increment=increment)
        self.hit += increment

    def increment_miss(self, *, increment: int = 1) -> None:
        self.increment(increment=increment)
        self.miss += increment


@dataclass
class GetStatistics(BaseHitMissStatistics):
    """A class for statistics about a KV Store collection."""


@dataclass
class PutStatistics(BaseStatistics):
    """A class for statistics about a KV Store collection."""


@dataclass
class DeleteStatistics(BaseHitMissStatistics):
    """A class for statistics about a KV Store collection."""


@dataclass
class ExistsStatistics(BaseHitMissStatistics):
    """A class for statistics about a KV Store collection."""


@dataclass
class TTLStatistics(BaseHitMissStatistics):
    """A class for statistics about a KV Store collection."""


@dataclass
class KVStoreCollectionStatistics(BaseStatistics):
    """A class for statistics about a KV Store collection."""

    get: GetStatistics = field(default_factory=GetStatistics)
    """The statistics for the get operation."""

    ttl: TTLStatistics = field(default_factory=TTLStatistics)
    """The statistics for the ttl operation."""

    put: PutStatistics = field(default_factory=PutStatistics)
    """The statistics for the put operation."""

    delete: DeleteStatistics = field(default_factory=DeleteStatistics)
    """The statistics for the delete operation."""

    exists: ExistsStatistics = field(default_factory=ExistsStatistics)
    """The statistics for the exists operation."""


@dataclass
class KVStoreStatistics:
    """Statistics container for a KV Store."""

    collections: dict[str, KVStoreCollectionStatistics] = field(default_factory=dict)

    def get_collection(self, collection: str) -> KVStoreCollectionStatistics:
        if collection not in self.collections:
            self.collections[collection] = KVStoreCollectionStatistics()
        return self.collections[collection]


class StatisticsWrapper(BaseWrapper):
    """Statistics wrapper around a KV Store that tracks operation statistics.

    Note: enumeration and destroy operations are not tracked by this wrapper.
    """

    def __init__(self, key_value: AsyncKeyValue) -> None:
        self.key_value: AsyncKeyValue = key_value
        self._statistics: KVStoreStatistics = KVStoreStatistics()

    @property
    def statistics(self) -> KVStoreStatistics:
        return self._statistics

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        collection = collection or DEFAULT_COLLECTION_NAME

        value = await self.key_value.get(collection=collection, key=key)

        if value is not None:
            self.statistics.get_collection(collection=collection).get.increment_hit()
            return value

        self.statistics.get_collection(collection=collection).get.increment_miss()

        return None

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        collection = collection or DEFAULT_COLLECTION_NAME

        value, ttl = await self.key_value.ttl(collection=collection, key=key)

        if value is not None:
            self.statistics.get_collection(collection=collection).ttl.increment_hit()
            return value, ttl

        self.statistics.get_collection(collection=collection).ttl.increment_miss()
        return None, None

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        collection = collection or DEFAULT_COLLECTION_NAME

        await self.key_value.put(collection=collection, key=key, value=value, ttl=ttl)

        self.statistics.get_collection(collection=collection).put.increment()

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        collection = collection or DEFAULT_COLLECTION_NAME

        if await self.key_value.delete(collection=collection, key=key):
            self.statistics.get_collection(collection=collection).delete.increment_hit()
            return True

        self.statistics.get_collection(collection=collection).delete.increment_miss()

        return False

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        collection = collection or DEFAULT_COLLECTION_NAME

        results: list[dict[str, Any] | None] = await self.key_value.get_many(keys=keys, collection=collection)

        hits = len([result for result in results if result is not None])
        misses = len([result for result in results if result is None])

        self.statistics.get_collection(collection=collection).get.increment_hit(increment=hits)
        self.statistics.get_collection(collection=collection).get.increment_miss(increment=misses)

        return results

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        collection = collection or DEFAULT_COLLECTION_NAME

        await self.key_value.put_many(keys=keys, values=values, collection=collection, ttl=ttl)

        self.statistics.get_collection(collection=collection).put.increment(increment=len(keys))

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        collection = collection or DEFAULT_COLLECTION_NAME

        deleted_count: int = await self.key_value.delete_many(keys=keys, collection=collection)

        hits = deleted_count
        misses = len(keys) - deleted_count

        self.statistics.get_collection(collection=collection).delete.increment_hit(increment=hits)
        self.statistics.get_collection(collection=collection).delete.increment_miss(increment=misses)

        return deleted_count

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        collection = collection or DEFAULT_COLLECTION_NAME

        results: list[tuple[dict[str, Any] | None, float | None]] = await self.key_value.ttl_many(keys=keys, collection=collection)

        hits = len([result for result in results if result[0] is not None])
        misses = len([result for result in results if result[0] is None])

        self.statistics.get_collection(collection=collection).ttl.increment_hit(increment=hits)
        self.statistics.get_collection(collection=collection).ttl.increment_miss(increment=misses)

        return results
