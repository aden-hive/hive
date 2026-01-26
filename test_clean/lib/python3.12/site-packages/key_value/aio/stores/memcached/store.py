from collections.abc import Sequence
from typing import overload

from key_value.shared.utils.compound import compound_key
from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.sanitization import HashExcessLengthStrategy, SanitizationStrategy
from typing_extensions import override

from key_value.aio.stores.base import BaseContextManagerStore, BaseDestroyStore, BaseStore

try:
    from aiomcache import Client
except ImportError as e:
    msg = "MemcachedStore requires py-key-value-aio[memcached]"
    raise ImportError(msg) from e

MAX_KEY_LENGTH = 240


class MemcachedV1KeySanitizationStrategy(HashExcessLengthStrategy):
    def __init__(self) -> None:
        super().__init__(max_length=MAX_KEY_LENGTH)


class MemcachedStore(BaseDestroyStore, BaseContextManagerStore, BaseStore):
    """Memcached-based key-value store using aiomcache.

    By default, keys are not sanitized. This means that there are character and length restrictions on
    keys that may cause errors when trying to get and put entries.

    To avoid issues, you may want to consider leveraging the `MemcachedV1KeySanitizationStrategy` strategy.
    """

    _client: Client

    @overload
    def __init__(
        self, *, client: Client, default_collection: str | None = None, key_sanitization_strategy: SanitizationStrategy | None = None
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11211,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None: ...

    def __init__(
        self,
        *,
        client: Client | None = None,
        host: str = "127.0.0.1",
        port: int = 11211,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the Memcached store.

        Args:
            client: An existing aiomcache client to use. If provided, the store will not manage
                the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            host: Memcached host. Defaults to 127.0.0.1.
            port: Memcached port. Defaults to 11211.
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
        """
        client_provided = client is not None

        if client is not None:
            self._client = client
        else:
            self._client = Client(host=host, port=port)

        super().__init__(
            default_collection=default_collection,
            key_sanitization_strategy=key_sanitization_strategy,
            client_provided_by_user=client_provided,
        )

    @override
    async def _setup(self) -> None:
        """Register client cleanup if we own the client."""
        if not self._client_provided_by_user:
            self._exit_stack.push_async_callback(self._client.close)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = self._sanitize_key(compound_key(collection=collection, key=key))

        raw_value: bytes | None = await self._client.get(combo_key.encode("utf-8"))

        if not isinstance(raw_value, (bytes, bytearray)):
            return None

        json_str: str = raw_value.decode(encoding="utf-8")

        return self._serialization_adapter.load_json(json_str=json_str)

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        if not keys:
            return []

        combo_keys: list[str] = [self._sanitize_key(compound_key(collection=collection, key=key)) for key in keys]

        # Use multi_get for efficient batch retrieval
        # multi_get returns a tuple in the same order as keys
        raw_values: tuple[bytes | None, ...] = await self._client.multi_get(*[k.encode("utf-8") for k in combo_keys])

        entries: list[ManagedEntry | None] = []
        for raw_value in raw_values:
            if isinstance(raw_value, (bytes, bytearray)):
                json_str: str = raw_value.decode(encoding="utf-8")
                entries.append(self._serialization_adapter.load_json(json_str=json_str))
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
        combo_key: str = self._sanitize_key(compound_key(collection=collection, key=key))

        # Memcached treats 0 as no-expiration. Do not pass <= 0 (other than 0) to avoid permanence errors.
        exptime: int

        if managed_entry.ttl is None:  # noqa: SIM108
            exptime = 0
        else:
            exptime = max(int(managed_entry.ttl), 1)

        json_value: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        _ = await self._client.set(
            key=combo_key.encode(encoding="utf-8"),
            value=json_value.encode(encoding="utf-8"),
            exptime=exptime,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = self._sanitize_key(compound_key(collection=collection, key=key))

        return await self._client.delete(key=combo_key.encode(encoding="utf-8"))

    @override
    async def _delete_store(self) -> bool:
        _ = await self._client.flush_all()
        return True
