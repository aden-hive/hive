from collections.abc import Callable, Mapping, Sequence
from typing import Any, SupportsFloat

from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper

RoutingFunction = Callable[[str | None], AsyncKeyValue | None]


class RoutingWrapper(BaseWrapper):
    """Routes operations to different stores based on a routing function.

    The routing function receives the collection name and returns the appropriate store.
    This allows dynamic routing of requests to different backing stores based on
    collection name or other custom logic.

    Example:
        def route_by_collection(collection: str | None) -> AsyncKeyValue | None:
            if collection == "sessions":
                return redis_store
            elif collection == "users":
                return dynamo_store
            return None

        router = RoutingWrapper(
            routing_function=route_by_collection,
            default_store=memory_store
        )
    """

    _routing_function: RoutingFunction
    _default_store: AsyncKeyValue

    def __init__(
        self,
        routing_function: RoutingFunction,
        default_store: AsyncKeyValue,
    ) -> None:
        """Initialize the routing wrapper.

        Args:
            routing_function: Function that takes a collection name and returns the store to use.
                             Should return None if no specific store is found.
            default_store: Fallback store if routing_function returns None.
        """
        self._routing_function = routing_function
        self._default_store = default_store

        super().__init__()

    def _get_store(self, collection: str | None) -> AsyncKeyValue:
        """Get the appropriate store for the given collection.

        Args:
            collection: The collection name to route.

        Returns:
            The AsyncKeyValue store to use for this collection.
        """
        store: AsyncKeyValue | None = self._routing_function(collection)
        if store is None:
            return self._default_store
        return store

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.get(key=key, collection=collection)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.get_many(keys=keys, collection=collection)

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.ttl(key=key, collection=collection)

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.ttl_many(keys=keys, collection=collection)

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.put(key=key, value=value, collection=collection, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.put_many(keys=keys, values=values, collection=collection, ttl=ttl)

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.delete(key=key, collection=collection)

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        store: AsyncKeyValue = self._get_store(collection)
        return await store.delete_many(keys=keys, collection=collection)
