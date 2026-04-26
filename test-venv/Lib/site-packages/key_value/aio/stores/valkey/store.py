from collections.abc import Sequence
from typing import overload

from typing_extensions import override

from key_value.aio._utils.compound import compound_key
from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio.stores.base import BaseContextManagerStore, BaseStore

try:
    from glide.glide_client import BaseClient, GlideClient, GlideClusterClient
    from glide_shared.commands.core_options import ExpirySet, ExpiryType
    from glide_shared.config import GlideClientConfiguration, GlideClusterClientConfiguration, NodeAddress, ServerCredentials
except ImportError as e:
    msg = "ValkeyStore requires py-key-value-aio[valkey]"
    raise ImportError(msg) from e


DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000


# Private helper functions to encapsulate Valkey/Glide client creation with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


def _create_valkey_client_config(
    *,
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    username: str | None = None,
    password: str | None = None,
) -> GlideClientConfiguration:
    """Create a Valkey client configuration."""
    addresses: list[NodeAddress] = [NodeAddress(host=host, port=port)]
    credentials: ServerCredentials | None = ServerCredentials(password=password, username=username) if password else None
    return GlideClientConfiguration(addresses=addresses, database_id=db, credentials=credentials)


async def _create_valkey_client(config: GlideClientConfiguration | GlideClusterClientConfiguration) -> GlideClient:
    """Create a Valkey client from configuration."""
    return await GlideClient.create(config=config)


async def _valkey_mget(client: BaseClient, keys: list[str]) -> list[bytes | None]:
    """Get multiple values from Valkey."""
    return await client.mget(keys=keys)  # pyright: ignore[reportArgumentType]


async def _valkey_delete(client: BaseClient, keys: list[str]) -> int:
    """Delete one or more keys from Valkey."""
    return await client.delete(keys=keys)  # pyright: ignore[reportArgumentType]


class ValkeyStore(BaseContextManagerStore, BaseStore):
    """Valkey-based key-value store (Redis protocol compatible).

    Supports both standalone (GlideClient) and cluster (GlideClusterClient) deployments.
    """

    _connected_client: BaseClient | None
    _client_config: GlideClientConfiguration | GlideClusterClientConfiguration | None

    @overload
    def __init__(self, *, client: GlideClient, default_collection: str | None = None) -> None: ...

    @overload
    def __init__(self, *, client: GlideClusterClient, default_collection: str | None = None) -> None: ...

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
            client: An existing Valkey client to use (GlideClient or GlideClusterClient).
                If provided, the store will not manage the client's lifecycle (will not
                close it). The caller is responsible for managing the client's lifecycle.
            default_collection: The default collection to use if no collection is provided.
            host: Valkey host. Defaults to localhost.
            port: Valkey port. Defaults to 6379.
            db: Valkey database number. Defaults to 0.
            username: Valkey username. Defaults to None.
            password: Valkey password. Defaults to None.

        Note:
            When using a cluster client, the host/port/db parameters are ignored.
            You must provide a pre-configured GlideClusterClient instance.
        """
        client_provided = client is not None

        if client is not None:
            self._connected_client = client
        else:
            self._client_config = _create_valkey_client_config(host=host, port=port, db=db, username=username, password=password)
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

            self._connected_client = await _create_valkey_client(self._client_config)

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

        responses: list[bytes | None] = await _valkey_mget(self._client, combo_keys)

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

        deleted_count: int = await _valkey_delete(self._client, combo_keys)

        return deleted_count
