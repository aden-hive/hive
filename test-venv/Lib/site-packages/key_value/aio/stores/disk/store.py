from datetime import datetime, timezone
from pathlib import Path
from typing import Any, overload

from typing_extensions import override

from key_value.aio._utils.compound import compound_key
from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio.stores.base import BaseContextManagerStore, BaseStore

try:
    from diskcache import Cache
except ImportError as e:
    msg = "DiskStore requires py-key-value-aio[disk]"
    raise ImportError(msg) from e


# Module-level helper functions for DiskStore cache operations


def _create_disk_cache(
    directory: Path,
    *,
    max_size: int | None = None,
) -> Cache:
    """Create a diskcache Cache instance.

    Args:
        directory: The directory to use for the cache.
        max_size: Optional maximum size limit. If None or 0, uses no eviction.

    Returns:
        A diskcache Cache instance.
    """
    if max_size is not None and max_size > 0:
        return Cache(directory=directory, size_limit=max_size)
    return Cache(directory=directory, eviction_policy="none")


def _disk_cache_get_with_expire(cache: Cache, key: str) -> tuple[Any, float | None]:
    """Get a value from the cache with its expiration time.

    Args:
        cache: The diskcache Cache instance.
        key: The key to retrieve.

    Returns:
        Tuple of (value, expire_time). Value is None if key doesn't exist.
    """
    return cache.get(key=key, expire_time=True)


def _disk_cache_set(
    cache: Cache,
    key: str,
    value: str,
    *,
    expire: float | None = None,
) -> bool:
    """Set a value in the cache.

    Args:
        cache: The diskcache Cache instance.
        key: The key to set.
        value: The value to store.
        expire: Optional expiration time in seconds.

    Returns:
        True if successful.
    """
    return cache.set(key=key, value=value, expire=expire)


def _disk_cache_delete(cache: Cache, key: str) -> bool:
    """Delete a key from the cache.

    Args:
        cache: The diskcache Cache instance.
        key: The key to delete.

    Returns:
        True if the key was deleted, False if it didn't exist.
    """
    return cache.delete(key=key, retry=True)


def _disk_cache_clear(cache: Cache) -> int:  # pyright: ignore[reportUnusedFunction] - Used by tests
    """Clear all items from the cache.

    Args:
        cache: The diskcache Cache instance.

    Returns:
        Number of items removed.
    """
    return cache.clear()


def _disk_cache_close(cache: Cache) -> None:
    """Close the cache.

    Args:
        cache: The diskcache Cache instance.
    """
    cache.close()


class DiskStore(BaseContextManagerStore, BaseStore):
    """A disk-based store that uses the diskcache library to store data."""

    _cache: Cache
    _auto_create: bool

    @overload
    def __init__(self, *, disk_cache: Cache, default_collection: str | None = None, auto_create: bool = True) -> None:
        """Initialize the disk store.

        Args:
            disk_cache: An existing diskcache Cache instance to use.
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the directory if it doesn't exist. Defaults to True.
        """

    @overload
    def __init__(
        self, *, directory: Path | str, max_size: int | None = None, default_collection: str | None = None, auto_create: bool = True
    ) -> None:
        """Initialize the disk store.

        Args:
            directory: The directory to use for the disk store.
            max_size: The maximum size of the disk store. Defaults to an unlimited size disk store
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the directory if it doesn't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        disk_cache: Cache | None = None,
        directory: Path | str | None = None,
        max_size: int | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the disk store.

        Args:
            disk_cache: An existing diskcache Cache instance to use. If provided, the store will
                not manage the cache's lifecycle (will not close it). The caller is responsible
                for managing the cache's lifecycle.
            directory: The directory to use for the disk store.
            max_size: The maximum size of the disk store.
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the directory if it doesn't exist. Defaults to True.
                When False, raises ValueError if the directory doesn't exist.
        """
        if disk_cache is not None and directory is not None:
            msg = "Provide only one of disk_cache or directory"
            raise ValueError(msg)

        if disk_cache is None and directory is None:
            msg = "Either disk_cache or directory must be provided"
            raise ValueError(msg)

        client_provided = disk_cache is not None
        self._client_provided_by_user = client_provided
        self._auto_create = auto_create

        if disk_cache:
            self._cache = disk_cache
        elif directory:
            directory = Path(directory)

            if not directory.exists():
                if not self._auto_create:
                    msg = f"Directory '{directory}' does not exist. Either create the directory manually or set auto_create=True."
                    raise ValueError(msg)
                directory.mkdir(parents=True, exist_ok=True)

            self._cache = _create_disk_cache(directory=directory, max_size=max_size)

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
            stable_api=True,
        )

    @override
    async def _setup(self) -> None:
        """Register cache cleanup if we own the cache."""
        if not self._client_provided_by_user:
            self._exit_stack.callback(lambda: _disk_cache_close(cache=self._cache))

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)

        expire_epoch: float | None

        managed_entry_str, expire_epoch = _disk_cache_get_with_expire(cache=self._cache, key=combo_key)

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
        combo_key: str = compound_key(collection=collection, key=key)

        _ = _disk_cache_set(
            cache=self._cache,
            key=combo_key,
            value=self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection),
            expire=managed_entry.ttl,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)

        return _disk_cache_delete(cache=self._cache, key=combo_key)

    def __del__(self) -> None:
        if not getattr(self, "_client_provided_by_user", False) and hasattr(self, "_cache"):
            _disk_cache_close(cache=self._cache)
