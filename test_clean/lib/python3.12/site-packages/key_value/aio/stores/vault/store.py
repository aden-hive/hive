"""HashiCorp Vault-based key-value store."""

from typing import overload

from key_value.shared.utils.compound import compound_key
from key_value.shared.utils.managed_entry import ManagedEntry
from typing_extensions import override

from key_value.aio.stores.base import BaseStore

try:
    import hvac
    from hvac.api.secrets_engines.kv_v2 import KvV2
    from hvac.exceptions import InvalidPath
except ImportError as e:
    msg = "VaultStore requires py-key-value-aio[vault]"
    raise ImportError(msg) from e


class VaultStore(BaseStore):
    """HashiCorp Vault-based key-value store using KV Secrets Engine v2.

    This store uses HashiCorp Vault's KV v2 secrets engine to persist key-value pairs.
    Each entry is stored as a secret in Vault with the combination of collection and key
    as the secret path.

    Note: The hvac library is synchronous, so operations are not truly async.
    """

    _client: hvac.Client
    _mount_point: str

    @overload
    def __init__(
        self,
        *,
        client: hvac.Client,
        mount_point: str = "secret",
        default_collection: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        url: str = "http://localhost:8200",
        token: str | None = None,
        mount_point: str = "secret",
        default_collection: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        *,
        client: hvac.Client | None = None,
        url: str = "http://localhost:8200",
        token: str | None = None,
        mount_point: str = "secret",
        default_collection: str | None = None,
    ) -> None:
        """Initialize the Vault store.

        Args:
            client: An existing hvac.Client instance. If provided, url and token are ignored.
            url: The URL of the Vault server. Defaults to "http://localhost:8200".
            token: The Vault token for authentication. If not provided, the client will
                attempt to use other authentication methods (e.g., environment variables).
            mount_point: The mount point for the KV v2 secrets engine. Defaults to "secret".
            default_collection: The default collection to use if no collection is provided.
        """
        if client is not None:
            self._client = client
        else:
            self._client = hvac.Client(url=url, token=token)

        self._mount_point = mount_point

        super().__init__(default_collection=default_collection)

    @property
    def _kv_v2(self) -> KvV2:
        return self._client.secrets.kv.v2  # pyright: ignore[reportUnknownMemberType,reportUnknownReturnType,reportUnknownVariableType]

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)

        try:
            response = self._kv_v2.read_secret(path=combo_key, mount_point=self._mount_point, raise_on_deleted_version=True)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except InvalidPath:
            return None
        except Exception:
            return None

        if response is None or "data" not in response or "data" not in response["data"]:  # pyright: ignore[reportUnknownVariableType]
            return None

        # Vault KV v2 returns data in response['data']['data']
        secret_data = response["data"]["data"]  # pyright: ignore[reportUnknownVariableType]

        if "value" not in secret_data:  # pyright: ignore[reportUnknownVariableType]
            return None

        json_str: str = secret_data["value"]  # pyright: ignore[reportUnknownVariableType]
        return self._serialization_adapter.load_json(json_str=json_str)  # pyright: ignore[reportUnknownArgumentType]

    @override
    async def _put_managed_entry(self, *, key: str, collection: str, managed_entry: ManagedEntry) -> None:
        combo_key: str = compound_key(collection=collection, key=key)

        json_str: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        # Store the JSON string in a 'value' field
        secret_data = {"value": json_str}

        self._kv_v2.create_or_update_secret(path=combo_key, secret=secret_data, mount_point=self._mount_point)  # pyright: ignore[reportUnknownMemberType]

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)

        try:
            # Vault doesnt tell us if the delete was successful so we read the entry and if it exists before we call delete,
            # we count it as a deletion.
            entry = self._kv_v2.read_secret(path=combo_key, mount_point=self._mount_point, raise_on_deleted_version=True)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            self._kv_v2.delete_metadata_and_all_versions(path=combo_key, mount_point=self._mount_point)  # pyright: ignore[reportUnknownMemberType]
        except InvalidPath:
            return False
        except Exception:
            return False

        return entry is not None
