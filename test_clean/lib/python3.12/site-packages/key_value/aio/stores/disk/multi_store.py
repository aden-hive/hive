from collections.abc import Callable
from datetime import timezone
from pathlib import Path
from typing import overload

from key_value.shared.utils.managed_entry import ManagedEntry, datetime
from key_value.shared.utils.serialization import BasicSerializationAdapter
from typing_extensions import override

from key_value.aio.stores.base import BaseContextManagerStore, BaseStore

try:
    from diskcache import Cache
    from pathvalidate import sanitize_filename
except ImportError as e:
    msg = "DiskStore requires py-key-value-aio[disk]"
    raise ImportError(msg) from e

CacheFactory = Callable[[str], Cache]


def _sanitize_collection_for_filesystem(collection: str) -> str:
    """Sanitize the collection name so that it can be used as a directory name on the filesystem."""

    return sanitize_filename(filename=collection)


class MultiDiskStore(BaseContextManagerStore, BaseStore):
    """A disk-based store that uses the diskcache library to store data. The MultiDiskStore by default creates
    one diskcache Cache instance per collection created by the caller but a custom factory function can be provided
    to tightly control the creation of the diskcache Cache instances."""

    _cache: dict[str, Cache]

    _disk_cache_factory: CacheFactory

    _base_directory: Path

    @overload
    def __init__(self, *, disk_cache_factory: CacheFactory, default_collection: str | None = None) -> None:
        """Initialize a multi-disk store with a custom factory function. The function will be called for each
        collection created by the caller with the collection name as the argument. Use this to tightly
        control the creation of the diskcache Cache instances.

        Args:
            disk_cache_factory: A factory function that creates a diskcache Cache instance for a given collection.
            default_collection: The default collection to use if no collection is provided.
        """

    @overload
    def __init__(self, *, base_directory: Path, max_size: int | None = None, default_collection: str | None = None) -> None:
        """Initialize a multi-disk store that creates one diskcache Cache instance per collection created by the caller.

        Args:
            base_directory: The directory to use for the disk caches.
            max_size: The maximum size of the disk caches.
            default_collection: The default collection to use if no collection is provided.
        """

    def __init__(
        self,
        *,
        disk_cache_factory: CacheFactory | None = None,
        base_directory: Path | None = None,
        max_size: int | None = None,
        default_collection: str | None = None,
    ) -> None:
        """Initialize the disk caches.

        Args:
            disk_cache_factory: A factory function that creates a diskcache Cache instance for a given collection.
            base_directory: The directory to use for the disk caches.
            max_size: The maximum size of the disk caches.
            default_collection: The default collection to use if no collection is provided.
        """
        if disk_cache_factory is None and base_directory is None:
            msg = "Either disk_cache_factory or base_directory must be provided"
            raise ValueError(msg)

        if base_directory is None:
            base_directory = Path.cwd()

        self._base_directory = base_directory.resolve()

        def default_disk_cache_factory(collection: str) -> Cache:
            """Create a default disk cache factory that creates a diskcache Cache instance for a given collection."""
            sanitized_collection: str = _sanitize_collection_for_filesystem(collection=collection)

            cache_directory: Path = self._base_directory / sanitized_collection

            cache_directory.mkdir(parents=True, exist_ok=True)

            if max_size is not None and max_size > 0:
                return Cache(directory=cache_directory, size_limit=max_size)

            return Cache(directory=cache_directory, eviction_policy="none")

        self._disk_cache_factory = disk_cache_factory or default_disk_cache_factory

        self._cache = {}

        self._serialization_adapter = BasicSerializationAdapter()

        super().__init__(
            default_collection=default_collection,
            stable_api=True,
        )

    @override
    async def _setup(self) -> None:
        """Register cache cleanup."""
        self._exit_stack.callback(self._sync_close)

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        self._cache[collection] = self._disk_cache_factory(collection)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        expire_epoch: float

        managed_entry_str, expire_epoch = self._cache[collection].get(key=key, expire_time=True)  # pyright: ignore[reportAny]

        if not isinstance(managed_entry_str, str):
            return None

        managed_entry: ManagedEntry = self._serialization_adapter.load_json(json_str=managed_entry_str)

        if expire_epoch:
            managed_entry.expires_at = datetime.fromtimestamp(expire_epoch, tz=timezone.utc)

        return managed_entry

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        _ = self._cache[collection].set(
            key=key,
            value=self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection),
            expire=managed_entry.ttl,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        return self._cache[collection].delete(key=key, retry=True)

    def _sync_close(self) -> None:
        for cache in self._cache.values():
            cache.close()

    def __del__(self) -> None:
        self._sync_close()
