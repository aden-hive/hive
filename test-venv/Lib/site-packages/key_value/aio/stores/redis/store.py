from collections.abc import Sequence
from datetime import datetime
from typing import Any, overload
from urllib.parse import urlparse

from typing_extensions import override

from key_value.aio._utils.beartype import bear_spray
from key_value.aio._utils.compound import compound_key, get_keys_from_compound_keys
from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.serialization import BasicSerializationAdapter, SerializationAdapter
from key_value.aio.errors import DeserializationError
from key_value.aio.stores.base import BaseContextManagerStore, BaseDestroyStore, BaseEnumerateKeysStore, BaseStore

try:
    from redis.asyncio import Redis
except ImportError as e:
    msg = "RedisStore requires py-key-value-aio[redis]"
    raise ImportError(msg) from e

DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000


# Private helper functions to encapsulate Redis client creation with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


def _create_redis_client(
    *,
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    username: str | None = None,
    password: str | None = None,
    decode_responses: bool = True,
) -> Redis:
    """Create a Redis client with the given parameters."""
    return Redis(
        host=host,
        port=port,
        db=db,
        username=username,
        password=password,
        decode_responses=decode_responses,
    )


def _create_redis_client_from_url(
    url: str,
    *,
    password: str | None = None,
    decode_responses: bool = True,
) -> Redis:
    """Create a Redis client from a URL.

    Args:
        url: Redis URL (e.g., redis://localhost:6379/0).
        password: Override password (used if not in URL).
        decode_responses: Whether to decode responses. Defaults to True.
    """
    parsed_url = urlparse(url)
    return Redis(
        host=parsed_url.hostname or "localhost",
        port=parsed_url.port or 6379,
        db=int(parsed_url.path.lstrip("/")) if parsed_url.path and parsed_url.path != "/" else 0,
        username=parsed_url.username,
        password=parsed_url.password or password,
        decode_responses=decode_responses,
    )


async def _redis_get(client: Redis, name: str) -> Any:
    """Get a value from Redis."""
    return await client.get(name=name)


async def _redis_mget(client: Redis, keys: list[str]) -> list[Any]:
    """Get multiple values from Redis."""
    return await client.mget(keys=keys)


async def _redis_set(client: Redis, name: str, value: str) -> None:
    """Set a value in Redis without TTL."""
    _ = await client.set(name=name, value=value)


async def _redis_setex(client: Redis, name: str, time: int, value: str) -> None:
    """Set a value in Redis with TTL."""
    _ = await client.setex(name=name, time=time, value=value)


async def _redis_pipeline_execute(pipeline: Any) -> None:
    """Execute a Redis pipeline."""
    await pipeline.execute()


async def _redis_delete(client: Redis, *keys: str) -> int:
    """Delete one or more keys from Redis."""
    return await client.delete(*keys)


async def _redis_scan(client: Redis, cursor: int, match: str, count: int) -> tuple[int, list[str]]:
    """Scan Redis keys matching a pattern."""
    return await client.scan(cursor=cursor, match=match, count=count)  # pyright: ignore[reportUnknownMemberType]


async def _redis_flushdb(client: Redis) -> bool:
    """Flush the current Redis database."""
    return await client.flushdb()  # pyright: ignore[reportUnknownMemberType]


class RedisStore(BaseDestroyStore, BaseEnumerateKeysStore, BaseContextManagerStore, BaseStore):
    """Redis-based key-value store."""

    _client: Redis
    _adapter: SerializationAdapter

    @overload
    def __init__(self, *, client: Redis, default_collection: str | None = None) -> None: ...

    @overload
    def __init__(self, *, url: str, default_collection: str | None = None) -> None: ...

    @overload
    def __init__(
        self, *, host: str = "localhost", port: int = 6379, db: int = 0, password: str | None = None, default_collection: str | None = None
    ) -> None: ...

    @bear_spray
    def __init__(
        self,
        *,
        client: Redis | None = None,
        default_collection: str | None = None,
        url: str | None = None,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ) -> None:
        """Initialize the Redis store.

        Args:
            client: An existing Redis client to use. If provided, the store will not manage
                the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            url: Redis URL (e.g., redis://localhost:6379/0).
            host: Redis host. Defaults to localhost.
            port: Redis port. Defaults to 6379.
            db: Redis database number. Defaults to 0.
            password: Redis password. Defaults to None.
            default_collection: The default collection to use if no collection is provided.
        """
        client_provided = client is not None

        if client:
            self._client = client
        elif url:
            self._client = _create_redis_client_from_url(url, password=password)
        else:
            self._client = _create_redis_client(host=host, port=port, db=db, password=password)

        self._adapter = BasicSerializationAdapter(date_format="isoformat", value_format="dict")

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
            stable_api=True,
        )

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)

        redis_response: Any = await _redis_get(self._client, combo_key)

        if not isinstance(redis_response, str):
            return None

        try:
            return self._adapter.load_json(json_str=redis_response)
        except DeserializationError:
            return None

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        if not keys:
            return []

        combo_keys: list[str] = [compound_key(collection=collection, key=key) for key in keys]

        redis_responses: list[Any] = await _redis_mget(self._client, combo_keys)

        entries: list[ManagedEntry | None] = []
        for redis_response in redis_responses:
            if isinstance(redis_response, str):
                try:
                    entries.append(self._adapter.load_json(json_str=redis_response))
                except DeserializationError:
                    entries.append(None)
            else:
                entries.append(None)

        return entries

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        combo_key: str = compound_key(collection=collection, key=key)

        json_value: str = self._adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        if managed_entry.ttl is not None:
            # Redis does not support <= 0 TTLs
            ttl = max(int(managed_entry.ttl), 1)

            await _redis_setex(self._client, combo_key, ttl, json_value)
        else:
            await _redis_set(self._client, combo_key, json_value)

    @override
    async def _put_managed_entries(
        self,
        *,
        collection: str,
        keys: Sequence[str],
        managed_entries: Sequence[ManagedEntry],
        ttl: float | None,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> None:
        if not keys:
            return

        if ttl is None:
            # If there is no TTL, we can just do a simple mset
            mapping: dict[str, str] = {}
            for key, managed_entry in zip(keys, managed_entries, strict=True):
                json_value = self._adapter.dump_json(entry=managed_entry, key=key, collection=collection)
                mapping[compound_key(collection=collection, key=key)] = json_value

            await self._client.mset(mapping=mapping)

            return

        # Convert TTL to integer seconds for Redis
        ttl_seconds: int = max(int(ttl), 1)

        # Use pipeline for bulk operations
        pipeline = self._client.pipeline()

        for key, managed_entry in zip(keys, managed_entries, strict=True):
            combo_key: str = compound_key(collection=collection, key=key)
            json_value = self._adapter.dump_json(entry=managed_entry, key=key, collection=collection)

            pipeline.setex(name=combo_key, time=ttl_seconds, value=json_value)

        await _redis_pipeline_execute(pipeline)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)

        return await _redis_delete(self._client, combo_key) != 0

    @override
    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        if not keys:
            return 0

        combo_keys: list[str] = [compound_key(collection=collection, key=key) for key in keys]

        deleted_count: int = await _redis_delete(self._client, *combo_keys)

        return deleted_count

    @override
    async def _get_collection_keys(self, *, collection: str, limit: int | None = None) -> list[str]:
        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)

        pattern = compound_key(collection=collection, key="*")

        # redis.asyncio scan returns tuple(cursor, keys)
        _cursor, keys = await _redis_scan(self._client, cursor=0, match=pattern, count=limit)

        return get_keys_from_compound_keys(compound_keys=keys, collection=collection)

    @override
    async def _setup(self) -> None:
        """Register client cleanup if we own the client."""
        if not self._client_provided_by_user:
            self._exit_stack.push_async_callback(self._client.aclose)

    @override
    async def _delete_store(self) -> bool:
        return await _redis_flushdb(self._client)
