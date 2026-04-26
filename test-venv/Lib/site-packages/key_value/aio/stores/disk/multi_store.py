from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.serialization import BasicSerializationAdapter
from key_value.aio.stores.base import BaseContextManagerStore, BaseStore
from key_value.aio.stores.disk.store import (
    _create_disk_cache,
    _disk_cache_close,
    _disk_cache_delete,
    _disk_cache_get_with_expire,
    _disk_cache_set,
)

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
    _auto_create: bool

    @overload
    def __init__(self, *, disk_cache_factory: CacheFactory, default_collection: str | None = None, auto_create: bool = True) -> None:
        """Initialize a multi-disk store with a custom factory function. The function will be called for each
        collection created by the caller with the collection name as the argument. Use this to tightly
        control the creation of the diskcache Cache instances.

        Args:
            disk_cache_factory: A factory function that creates a diskcache Cache instance for a given collection.
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create directories if they don't exist. Defaults to True.
        """

    @overload
    def __init__(
        self, *, base_directory: Path, max_size: int | None = None, default_collection: str | None = None, auto_create: bool = True
    ) -> None:
        """Initialize a multi-disk store that creates one diskcache Cache instance per collection created by the caller.

        Args:
            base_directory: The directory to use for the disk caches.
            max_size: The maximum size of the disk caches.
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create directories if they don't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        disk_cache_factory: CacheFactory | None = None,
        base_directory: Path | None = None,
        max_size: int | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the disk caches.

        Args:
            disk_cache_factory: A factory function that creates a diskcache Cache instance for a given collection.
            base_directory: The directory to use for the disk caches.
            max_size: The maximum size of the disk caches.
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create directories if they don't exist. Defaults to True.
                When False, raises ValueError if a directory doesn't exist.
        """
        if disk_cache_factory is None and base_directory is None:
            msg = "Either disk_cache_factory or base_directory must be provided"
            raise ValueError(msg)

        if base_directory is None:
            base_directory = Path.cwd()

        self._base_directory = base_directory.resolve()
        self._auto_create = auto_create

        def default_disk_cache_factory(collection: str) -> Cache:
            """Create a default disk cache factory that creates a diskcache Cache instance for a given collection."""
            sanitized_collection: str = _sanitize_collection_for_filesystem(collection=collection)

            cache_directory: Path = self._base_directory / sanitized_collection

            if not cache_directory.exists():
                if not self._auto_create:
                    msg = f"Directory '{cache_directory}' does not exist. Either create the directory manually or set auto_create=True."
                    raise ValueError(msg)
                cache_directory.mkdir(parents=True, exist_ok=True)

            return _create_disk_cache(directory=cache_directory, max_size=max_size)

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
        expire_epoch: float | None

        managed_entry_str, expire_epoch = _disk_cache_get_with_expire(cache=self._cache[collection], key=key)

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
        _ = _disk_cache_set(
            cache=self._cache[collection],
            key=key,
            value=self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection),
            expire=managed_entry.ttl,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        return _disk_cache_delete(cache=self._cache[collection], key=key)

    def _sync_close(self) -> None:
        for cache in self._cache.values():
            _disk_cache_close(cache=cache)

    def __del__(self) -> None:
        self._sync_close()
