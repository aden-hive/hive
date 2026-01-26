import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.serialization import BasicSerializationAdapter
from typing_extensions import override

from key_value.aio.stores.base import (
    SEED_DATA_TYPE,
    BaseDestroyCollectionStore,
    BaseDestroyStore,
    BaseEnumerateCollectionsStore,
    BaseEnumerateKeysStore,
)

try:
    from cachetools import TLRUCache
except ImportError as e:
    msg = "MemoryStore requires py-key-value-aio[memory]"
    raise ImportError(msg) from e


@dataclass
class MemoryCacheEntry:
    """A cache entry for the memory store."""

    json_str: str

    expires_at: datetime | None


def _memory_cache_ttu(_key: Any, value: MemoryCacheEntry, _now: float) -> float:
    """Calculate time-to-use for cache entries based on their expiration time."""
    if value.expires_at is None:
        return float(sys.maxsize)

    return value.expires_at.timestamp()


def _memory_cache_getsizeof(value: MemoryCacheEntry) -> int:  # noqa: ARG001
    """Return size of cache entry (always 1 for entry counting)."""
    return 1


DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000


class MemoryCollection:
    _cache: TLRUCache[str, MemoryCacheEntry]

    def __init__(self, max_entries: int | None = None):
        """Initialize a fixed-size in-memory collection.

        Args:
            max_entries: The maximum number of entries per collection. Defaults to no limit.
        """
        self._cache = TLRUCache[str, MemoryCacheEntry](
            maxsize=max_entries if max_entries is not None else sys.maxsize,
            ttu=_memory_cache_ttu,
            getsizeof=_memory_cache_getsizeof,
        )

        self._serialization_adapter = BasicSerializationAdapter()

    def get(self, key: str) -> ManagedEntry | None:
        managed_entry_str: MemoryCacheEntry | None = self._cache.get(key)

        if managed_entry_str is None:
            return None

        managed_entry: ManagedEntry = self._serialization_adapter.load_json(json_str=managed_entry_str.json_str)

        return managed_entry

    def put(self, key: str, value: ManagedEntry) -> None:
        json_str: str = self._serialization_adapter.dump_json(entry=value)
        self._cache[key] = MemoryCacheEntry(json_str=json_str, expires_at=value.expires_at)

    def delete(self, key: str) -> bool:
        return self._cache.pop(key, None) is not None

    def keys(self, *, limit: int | None = None) -> list[str]:
        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)
        return list(self._cache.keys())[:limit]


class MemoryStore(BaseDestroyStore, BaseDestroyCollectionStore, BaseEnumerateCollectionsStore, BaseEnumerateKeysStore):
    """A fixed-size in-memory key-value store using TLRU (Time-aware Least Recently Used) cache."""

    max_entries_per_collection: int

    _cache: dict[str, MemoryCollection]

    def __init__(
        self,
        *,
        max_entries_per_collection: int | None = None,
        default_collection: str | None = None,
        seed: SEED_DATA_TYPE | None = None,
    ):
        """Initialize a fixed-size in-memory store.

        Args:
            max_entries_per_collection: The maximum number of entries per collection. Defaults to no limit.
            default_collection: The default collection to use if no collection is provided.
            seed: Optional seed data to pre-populate the store. Format: {collection: {key: {field: value, ...}}}.
                Each value must be a mapping (dict) that will be stored as the entry's value.
                Seeding occurs lazily when each collection is first accessed.
        """

        self.max_entries_per_collection = max_entries_per_collection if max_entries_per_collection is not None else sys.maxsize

        self._cache = {}

        super().__init__(
            default_collection=default_collection,
            seed=seed,
            stable_api=True,
        )

    @override
    async def _setup(self) -> None:
        for collection in self._seed:
            await self._setup_collection(collection=collection)

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        """Set up a collection, creating it and seeding it if seed data is available.

        Args:
            collection: The collection name.
        """
        if collection in self._cache:
            return

        collection_cache = MemoryCollection(max_entries=self.max_entries_per_collection)
        self._cache[collection] = collection_cache

    def _get_collection_or_raise(self, collection: str) -> MemoryCollection:
        """Get a collection or raise KeyError if not setup.

        Args:
            collection: The collection name.

        Returns:
            The MemoryCollection instance.

        Raises:
            KeyError: If the collection has not been setup via setup_collection().
        """
        collection_cache: MemoryCollection | None = self._cache.get(collection)
        if collection_cache is None:
            msg = f"Collection '{collection}' has not been setup. Call setup_collection() first."
            raise KeyError(msg)
        return collection_cache

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        collection_cache = self._get_collection_or_raise(collection)
        return collection_cache.get(key=key)

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        collection_cache = self._get_collection_or_raise(collection)
        collection_cache.put(key=key, value=managed_entry)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        collection_cache = self._get_collection_or_raise(collection)
        return collection_cache.delete(key=key)

    @override
    async def _get_collection_keys(self, *, collection: str, limit: int | None = None) -> list[str]:
        collection_cache = self._get_collection_or_raise(collection)
        return collection_cache.keys(limit=limit)

    @override
    async def _get_collection_names(self, *, limit: int | None = None) -> list[str]:
        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)
        return list(self._cache.keys())[:limit]

    @override
    async def _delete_collection(self, *, collection: str) -> bool:
        if collection not in self._cache:
            return False

        del self._cache[collection]

        return True

    @override
    async def _delete_store(self) -> bool:
        self._cache.clear()

        return True
