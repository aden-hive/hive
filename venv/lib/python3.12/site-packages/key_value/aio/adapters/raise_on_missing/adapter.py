from collections.abc import Mapping, Sequence
from typing import Any, Literal, SupportsFloat, overload

from key_value.shared.errors import MissingKeyError

from key_value.aio.protocols.key_value import AsyncKeyValue


class RaiseOnMissingAdapter:
    """Adapter around a KVStore that raises on missing values for get/get_many/ttl/ttl_many.

    When `raise_on_missing=True`, methods raise `MissingKeyError` instead of returning None.
    """

    def __init__(self, key_value: AsyncKeyValue) -> None:
        self.key_value: AsyncKeyValue = key_value

    @overload
    async def get(self, key: str, *, collection: str | None = None, raise_on_missing: Literal[False] = False) -> dict[str, Any] | None: ...

    @overload
    async def get(self, key: str, *, collection: str | None = None, raise_on_missing: Literal[True]) -> dict[str, Any]: ...

    async def get(
        self,
        key: str,
        *,
        collection: str | None = None,
        raise_on_missing: bool = False,
    ) -> dict[str, Any] | None:
        """Retrieve a value by key from the specified collection.

        Args:
            key: The key to retrieve the value from.
            collection: The collection to retrieve the value from. If no collection is provided, it will use the default collection.
            raise_on_missing: Whether to raise a MissingKeyError if the key is not found.

        Returns:
            The value associated with the key. If the key is not found, None will be returned.
        """
        result = await self.key_value.get(key=key, collection=collection)

        if result is not None:
            return result

        if raise_on_missing:
            raise MissingKeyError(operation="get", collection=collection, key=key)

        return None

    @overload
    async def get_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: Literal[False] = False
    ) -> list[dict[str, Any] | None]: ...

    @overload
    async def get_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: Literal[True]
    ) -> list[dict[str, Any]]: ...

    async def get_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: bool = False
    ) -> list[dict[str, Any]] | list[dict[str, Any] | None]:
        """Retrieve multiple values by key from the specified collection.

        Args:
            keys: The keys to retrieve the values from.
            collection: The collection to retrieve keys from. If no collection is provided, it will use the default collection.

        Returns:
            The values for the keys, or [] if the key is not found.
        """
        results: list[dict[str, Any] | None] = await self.key_value.get_many(collection=collection, keys=keys)

        for i, key in enumerate(keys):
            if results[i] is None and raise_on_missing:
                raise MissingKeyError(operation="get_many", collection=collection, key=key)

        return results

    @overload
    async def ttl(
        self, key: str, *, collection: str | None = None, raise_on_missing: Literal[False] = False
    ) -> tuple[dict[str, Any] | None, float | None]: ...

    @overload
    async def ttl(
        self, key: str, *, collection: str | None = None, raise_on_missing: Literal[True]
    ) -> tuple[dict[str, Any], float | None]: ...

    async def ttl(
        self, key: str, *, collection: str | None = None, raise_on_missing: bool = False
    ) -> tuple[dict[str, Any] | None, float | None]:
        """Retrieve the value and TTL information for a key-value pair from the specified collection.

        Args:
            key: The key to retrieve the TTL information from.
            collection: The collection to retrieve the TTL information from. If no collection is provided,
                        it will use the default collection.

        Returns:
            The value and TTL information for the key. If the key is not found, (None, None) will be returned.
        """
        value, ttl = await self.key_value.ttl(key=key, collection=collection)

        if value is not None:
            return value, ttl

        if raise_on_missing:
            raise MissingKeyError(operation="ttl", collection=collection, key=key)

        return (None, None)

    @overload
    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: Literal[False] = False
    ) -> list[tuple[dict[str, Any] | None, float | None]]: ...

    @overload
    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: Literal[True]
    ) -> list[tuple[dict[str, Any], float | None]]: ...

    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None, raise_on_missing: bool = False
    ) -> list[tuple[dict[str, Any], float | None]] | list[tuple[dict[str, Any] | None, float | None]]:
        """Retrieve multiple values and TTL information by key from the specified collection.

        Args:
            keys: The keys to retrieve the values and TTL information from.
            collection: The collection to retrieve keys from. If no collection is provided, it will use the default collection.
        """
        results: list[tuple[dict[str, Any] | None, float | None]] = await self.key_value.ttl_many(collection=collection, keys=keys)

        for i, key in enumerate(keys):
            if results[i][0] is None and raise_on_missing:
                raise MissingKeyError(operation="ttl_many", collection=collection, key=key)

        return results

    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        """Store a key-value pair in the specified collection with optional TTL.

        Args:
            key: The key to store the value in.
            value: The value to store.
            collection: The collection to store the value in. If no collection is provided, it will use the default collection.
            ttl: The optional time-to-live (expiry duration) for the key-value pair. Defaults to no TTL. Note: The
                backend store will convert the provided format to its own internal format.
        """
        return await self.key_value.put(key=key, value=value, collection=collection, ttl=ttl)

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
            ttl: The optional time-to-live (expiry duration) for all key-value pairs. The same TTL will be applied to all
                items in the batch. Defaults to no TTL. Note: The backend store will convert the provided format to its own
                internal format.
        """
        return await self.key_value.put_many(keys=keys, values=values, collection=collection, ttl=ttl)

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        """Delete a key-value pair from the specified collection.

        Args:
            key: The key to delete the value from.
            collection: The collection to delete the value from. If no collection is provided, it will use the default collection.
        """
        return await self.key_value.delete(key=key, collection=collection)

    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        """Delete multiple key-value pairs from the specified collection.

        Args:
            keys: The keys to delete the values from.
            collection: The collection to delete keys from. If no collection is provided, it will use the default collection.

        Returns:
            The number of keys deleted.
        """
        return await self.key_value.delete_many(keys=keys, collection=collection)
