from collections.abc import Mapping, Sequence
from typing import Any, Protocol, SupportsFloat, runtime_checkable


@runtime_checkable
class AsyncKeyValueProtocol(Protocol):
    """A subset of KV operations: get/put/delete and TTL variants, including bulk calls.

    This protocol defines the minimal contract for key-value store implementations. All methods may
    raise exceptions on connection failures, validation errors, or other operational issues.

    Implementations should handle backend-specific errors appropriately.
    """

    async def get(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a value by key from the specified collection.

        Args:
            key: The key to retrieve the value from.
            collection: The collection to retrieve the value from. If no collection is provided, it will use the default collection.

        Returns:
            The value associated with the key. If the key is not found, None will be returned.
        """
        ...

    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        """Retrieve the value and TTL information for a key-value pair from the specified collection.

        Args:
            key: The key to retrieve the TTL information from.
            collection: The collection to retrieve the TTL information from. If no collection is provided,
                        it will use the default collection.

        Returns:
            The value and TTL information for the key. If the key is not found, (None, None) will be returned.
        """
        ...

    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        """Store a key-value pair in the specified collection with optional TTL.

        Args:
            key: The key to store the value in.
            value: The value to store.
            collection: The collection to store the value in. If no collection is provided, it will use the default collection.
            ttl: The optional time-to-live (expiry duration) in seconds for the key-value pair. Defaults to no TTL. Note: The
                backend store will convert the provided format to its own internal format.
        """
        ...

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        """Delete a key-value pair from the specified collection.

        Args:
            key: The key to delete the value from.
            collection: The collection to delete the value from. If no collection is provided, it will use the default collection.

        Returns:
            True if the key was deleted, False if the key did not exist.
        """
        ...

    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        """Retrieve multiple values by key from the specified collection.

        Args:
            keys: The keys to retrieve the values from.
            collection: The collection to retrieve keys from. If no collection is provided, it will use the default collection.

        Returns:
            A list of values for the keys. Each value is either a dict or None if the key is not found.
        """
        ...

    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        """Retrieve multiple values and TTL information by key from the specified collection.

        Args:
            keys: The keys to retrieve the values and TTL information from.
            collection: The collection to retrieve keys from. If no collection is provided, it will use the default collection.

        Returns:
            A list of tuples containing (value, ttl) for each key. Each tuple contains either (dict, float) or (None, None) if the
            key is not found.
        """
        ...

    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        """Store multiple key-value pairs in the specified collection.

        Args:
            keys: The keys to store the values in.
            values: The values to store.
            collection: The collection to store keys in. If no collection is provided, it will use the default collection.
            ttl: The optional time-to-live (expiry duration) in seconds for all key-value pairs. The same TTL will be applied
                to all items in the batch. Defaults to no TTL. Note: The backend store will convert the provided format to
                its own internal format.
        """
        ...

    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        """Delete multiple key-value pairs from the specified collection.

        Args:
            keys: The keys to delete the values from.
            collection: The collection to delete keys from. If no collection is provided, it will use the default collection.

        Returns:
            The number of keys deleted.
        """
        ...


@runtime_checkable
class AsyncCullProtocol(Protocol):
    async def cull(self) -> None:
        """Cull the store.

        This will remove all expired keys from the store.
        """
        ...


@runtime_checkable
class AsyncEnumerateKeysProtocol(Protocol):
    """Protocol segment to enumerate keys in a collection."""

    async def keys(self, collection: str | None = None, *, limit: int | None = None) -> list[str]:
        """List all keys in the specified collection.

        Args:
            collection: The collection to list the keys from. If no collection is provided, it will use the default collection.
            limit: The maximum number of keys to list. The behavior when no limit is provided is store-dependent.
        """
        ...


@runtime_checkable
class AsyncEnumerateCollectionsProtocol(Protocol):
    async def collections(self, *, limit: int | None = None) -> list[str]:
        """List all available collection names (may include empty collections).

        Args:
            limit: The maximum number of collections to list. The behavior when no limit is provided is store-dependent.
        """
        ...


@runtime_checkable
class AsyncDestroyStoreProtocol(Protocol):
    """Protocol segment for store-destruction semantics."""

    async def destroy(self) -> bool:
        """Destroy the keystore.

        This will clear all collections and keys from the store.
        """
        ...


@runtime_checkable
class AsyncDestroyCollectionProtocol(Protocol):
    async def destroy_collection(self, collection: str) -> bool:
        """Destroy the specified collection.

        Args:
            collection: The collection to destroy.
        """
        ...


class AsyncKeyValue(AsyncKeyValueProtocol, Protocol):
    """A protocol for key-value store operations.

    Includes basic operations: get, put, delete, ttl
    Includes bulk operations: get_many, put_many, delete_many, ttl_many.
    """
