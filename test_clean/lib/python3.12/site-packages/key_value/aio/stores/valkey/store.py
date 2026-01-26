from collections.abc import Sequence
from typing import overload

from key_value.shared.utils.compound import compound_key
from key_value.shared.utils.managed_entry import ManagedEntry
from typing_extensions import override

from key_value.aio.stores.base import BaseContextManagerStore, BaseStore

try:
    from glide.glide_client import BaseClient, GlideClient
    from glide_shared.commands.core_options import ExpirySet, ExpiryType
    from glide_shared.config import GlideClientConfiguration, NodeAddress, ServerCredentials
except ImportError as e:
    msg = "ValkeyStore requires py-key-value-aio[valkey]"
    raise ImportError(msg) from e


DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000


class ValkeyStore(BaseContextManagerStore, BaseStore):
    """Valkey-based key-value store (Redis protocol compatible)."""

    _connected_client: BaseClient | None
    _client_config: GlideClientConfiguration | None

    @overload
    def __init__(self, *, client: BaseClient, default_collection: str | None = None) -> None: ...

    @overload
    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        username: str | None = None,
        password: str | None = None,
        default_collection: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        *,
        client: BaseClient | None = None,
        default_collection: str | None = None,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the Valkey store.

        Args:
            client: An existing Valkey client to use. If provided, the store will not manage
                the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            default_collection: The default collection to use if no collection is provided.
            host: Valkey host. Defaults to localhost.
            port: Valkey port. Defaults to 6379.
            db: Valkey database number. Defaults to 0.
            username: Valkey username. Defaults to None.
            password: Valkey password. Defaults to None.
        """
        client_provided = client is not None

        if client is not None:
            self._connected_client = client
        else:
            # redis client accepts URL
            addresses: list[NodeAddress] = [NodeAddress(host=host, port=port)]
            credentials: ServerCredentials | None = ServerCredentials(password=password, username=username) if password else None
            self._client_config = GlideClientConfiguration(addresses=addresses, database_id=db, credentials=credentials)
            self._connected_client = None

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
            stable_api=True,
        )

    @override
    async def _setup(self) -> None:
        if self._connected_client is None:
            if self._client_config is None:
                # This should never happen, makes the type checker happy though
                msg = "Client configuration is not set"
                raise ValueError(msg)

            self._connected_client = await GlideClient.create(config=self._client_config)

        # Register client cleanup if we own the client
        if not self._client_provided_by_user:
            self._exit_stack.push_async_callback(self._client.close)

    @property
    def _client(self) -> BaseClient:
        if self._connected_client is None:
            # This should never happen, makes the type checker happy though
            msg = "Client is not connected"
            raise ValueError(msg)

        return self._connected_client

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)

        response: bytes | None = await self._client.get(key=combo_key)

        if not isinstance(response, bytes):
            return None

        decoded_response: str = response.decode("utf-8")

        return self._serialization_adapter.load_json(json_str=decoded_response)

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        if not keys:
            return []

        combo_keys: list[str] = [compound_key(collection=collection, key=key) for key in keys]

        responses: list[bytes | None] = await self._client.mget(keys=combo_keys)  # pyright: ignore[reportUnknownMemberType, reportArgumentType]

        entries: list[ManagedEntry | None] = []
        for response in responses:
            if isinstance(response, bytes):
                decoded_response: str = response.decode("utf-8")
                entries.append(self._serialization_adapter.load_json(json_str=decoded_response))
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

        json_value: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        expiry: ExpirySet | None = ExpirySet(expiry_type=ExpiryType.SEC, value=int(managed_entry.ttl)) if managed_entry.ttl else None

        _ = await self._client.set(key=combo_key, value=json_value, expiry=expiry)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)
        return await self._client.delete(keys=[combo_key]) != 0

    @override
    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        if not keys:
            return 0

        combo_keys: list[str] = [compound_key(collection=collection, key=key) for key in keys]

        deleted_count: int = await self._client.delete(keys=combo_keys)  # pyright: ignore[reportArgumentType]

        return deleted_count
