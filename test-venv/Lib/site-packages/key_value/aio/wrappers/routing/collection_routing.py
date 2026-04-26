from collections.abc import Mapping
from types import MappingProxyType

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.routing.wrapper import RoutingWrapper


class CollectionRoutingWrapper(RoutingWrapper):
    """Routes operations based on collection name using a simple map.

    This is a convenience wrapper that provides collection-based routing using a
    dictionary mapping collection names to stores. This is useful for directing
    different data types to different backing stores.

    Example:
        router = CollectionRoutingWrapper(
            collection_map={
                "sessions": redis_store,
                "users": dynamo_store,
                "cache": memory_store,
            },
            default_store=disk_store
        )
    """

    _collection_map: MappingProxyType[str, AsyncKeyValue]

    def __init__(
        self,
        collection_map: Mapping[str, AsyncKeyValue],
        default_store: AsyncKeyValue,
    ) -> None:
        """Initialize collection-based routing.

        Args:
            collection_map: Mapping from collection name to store. Each collection
                           name is mapped to its corresponding backing store.
            default_store: Store to use for unmapped collections.
        """
        self._collection_map = MappingProxyType(mapping=dict(collection_map))

        def route_by_collection(collection: str | None) -> AsyncKeyValue | None:
            if collection is not None:
                return self._collection_map.get(collection)

            return None

        super().__init__(
            routing_function=route_by_collection,
            default_store=default_store,
        )
