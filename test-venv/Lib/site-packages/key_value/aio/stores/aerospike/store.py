from typing import Any, overload

from typing_extensions import override

from key_value.aio._utils.compound import compound_key, get_keys_from_compound_keys
from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.serialization import BasicSerializationAdapter
from key_value.aio.errors import DeserializationError
from key_value.aio.stores.base import BaseContextManagerStore, BaseDestroyStore, BaseEnumerateKeysStore, BaseStore

try:
    import aerospike
except ImportError as e:
    msg = "AerospikeStore requires py-key-value-aio[aerospike]"
    raise ImportError(msg) from e

DEFAULT_NAMESPACE = "test"
DEFAULT_SET = "kv-store"
DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000


# Private helper functions to encapsulate aerospike client interactions with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


def _create_aerospike_client(config: dict[str, Any]) -> aerospike.Client:
    """Create an Aerospike client."""
    return aerospike.client(config)  # pyright: ignore[reportUnknownMemberType]


def _connect_aerospike_client(client: aerospike.Client) -> None:
    """Connect the Aerospike client."""
    client.connect()


def _get_aerospike_record(
    client: aerospike.Client,
    aerospike_key: tuple[str, str, str],
) -> tuple[Any, Any, dict[str, Any]] | None:
    """Get a record from Aerospike.

    Returns:
        Tuple of (key, metadata, bins) or None if not found.
    """
    try:
        return client.get(aerospike_key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except aerospike.exception.RecordNotFound:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
        return None


def _put_aerospike_record(
    client: aerospike.Client,
    aerospike_key: tuple[str, str, str],
    bins: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> None:
    """Put a record into Aerospike."""
    if meta:
        client.put(aerospike_key, bins, meta=meta)  # pyright: ignore[reportUnknownMemberType]
    else:
        client.put(aerospike_key, bins)  # pyright: ignore[reportUnknownMemberType]


def _remove_aerospike_record(
    client: aerospike.Client,
    aerospike_key: tuple[str, str, str],
) -> bool:
    """Remove a record from Aerospike.

    Returns:
        True if the record was deleted, False if it didn't exist.
    """
    try:
        client.remove(aerospike_key)  # pyright: ignore[reportUnknownMemberType]
    except aerospike.exception.RecordNotFound:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
        return False
    else:
        return True


def _scan_aerospike_set(
    client: aerospike.Client,
    namespace: str,
    set_name: str,
    callback: Any,
) -> None:
    """Scan the entire set with a callback function."""
    scan = client.scan(namespace, set_name)
    scan.foreach(callback)  # pyright: ignore[reportUnknownMemberType]


def _truncate_aerospike_set(
    client: aerospike.Client,
    namespace: str,
    set_name: str,
) -> None:
    """Truncate the set (delete all records)."""
    client.truncate(namespace, set_name, 0)  # pyright: ignore[reportUnknownMemberType]


def _close_aerospike_client(client: aerospike.Client) -> None:
    """Close the Aerospike client connection."""
    client.close()


def _get_aerospike_namespaces(client: aerospike.Client) -> list[str]:
    """Get the list of available namespaces from the cluster.

    Returns:
        List of namespace names.
    """
    info_response: dict[str, tuple[int, str]] = client.info_all("namespaces")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    # info_all returns {(host, port, None): (error_code, response_string), ...}
    # response_string for 'namespaces' is a semicolon-separated list of namespace names
    namespaces: set[str] = set()
    for error_code, response in info_response.values():
        if error_code == 0 and response:
            namespaces.update(response.split(";"))
    return list(namespaces)


class AerospikeStore(BaseDestroyStore, BaseEnumerateKeysStore, BaseContextManagerStore, BaseStore):
    """Aerospike-based key-value store.

    Note: Aerospike namespaces must be pre-configured on the server. Sets are created
    automatically when the first record is written.

    When `auto_create=False`, the store will verify that the configured namespace exists
    during setup and raise a ValueError if it doesn't.
    """

    _client: aerospike.Client
    _namespace: str
    _set: str
    _auto_create: bool

    @overload
    def __init__(
        self,
        *,
        client: aerospike.Client,
        namespace: str = DEFAULT_NAMESPACE,
        set_name: str = DEFAULT_SET,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the Aerospike store.

        Args:
            client: The Aerospike client to use. You must have connected the client before passing this in.
            namespace: Aerospike namespace. Defaults to "test".
            set_name: Aerospike set. Defaults to "kv-store".
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to skip namespace validation. When False, verifies the namespace
                exists during setup. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        hosts: list[tuple[str, int]] | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        set_name: str = DEFAULT_SET,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the Aerospike store.

        Args:
            hosts: List of (host, port) tuples. Defaults to [("localhost", 3000)].
            namespace: Aerospike namespace. Defaults to "test".
            set_name: Aerospike set. Defaults to "kv-store".
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to skip namespace validation. When False, verifies the namespace
                exists during setup. Defaults to True.
        """

    def __init__(
        self,
        *,
        client: aerospike.Client | None = None,
        hosts: list[tuple[str, int]] | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        set_name: str = DEFAULT_SET,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the Aerospike store.

        Args:
            client: An existing Aerospike client to use. If provided, the store will not manage
                the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            hosts: List of (host, port) tuples. Defaults to [("localhost", 3000)].
            namespace: Aerospike namespace. Defaults to "test".
            set_name: Aerospike set. Defaults to "kv-store".
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to skip namespace validation. When False, verifies the namespace
                exists during setup. Defaults to True. Note that Aerospike namespaces must be
                pre-configured on the server; this option only controls validation.
        """
        client_provided = client is not None

        if client:
            self._client = client
        else:
            hosts = hosts or [("localhost", 3000)]
            config = {"hosts": hosts}
            self._client = _create_aerospike_client(config)

        self._namespace = namespace
        self._set = set_name
        self._auto_create = auto_create

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
            serialization_adapter=BasicSerializationAdapter(date_format="isoformat", value_format="dict"),
            stable_api=True,
        )

    @override
    async def _setup(self) -> None:
        """Connect to Aerospike and register cleanup."""
        _connect_aerospike_client(self._client)

        # Register client cleanup if we own the client
        if not self._client_provided_by_user:
            self._exit_stack.callback(lambda: _close_aerospike_client(self._client))

        # Verify namespace exists if auto_create is False
        if not self._auto_create:
            namespaces = _get_aerospike_namespaces(self._client)
            if self._namespace not in namespaces:
                msg = (
                    f"Namespace '{self._namespace}' does not exist. "
                    "Either configure the namespace on the Aerospike server or set auto_create=True."
                )
                raise ValueError(msg)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)
        aerospike_key = (self._namespace, self._set, combo_key)

        record = _get_aerospike_record(self._client, aerospike_key)
        if record is None:
            return None

        (_key, _metadata, bins) = record
        json_value: str | None = bins.get("value")

        if not isinstance(json_value, str):
            return None

        try:
            return self._serialization_adapter.load_json(json_str=json_value)
        except DeserializationError:
            return None

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        combo_key: str = compound_key(collection=collection, key=key)
        aerospike_key = (self._namespace, self._set, combo_key)
        json_value: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        bins = {"value": json_value}

        meta = None
        if managed_entry.ttl is not None:
            # Aerospike TTL is in seconds
            meta = {"ttl": int(managed_entry.ttl)}

        _put_aerospike_record(self._client, aerospike_key, bins, meta=meta)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)
        aerospike_key = (self._namespace, self._set, combo_key)

        return _remove_aerospike_record(self._client, aerospike_key)

    @override
    async def _get_collection_keys(self, *, collection: str, limit: int | None = None) -> list[str]:
        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)

        pattern = compound_key(collection=collection, key="")

        keys: list[str] = []

        def callback(record: tuple[Any, Any, Any]) -> None:
            # Aerospike scan callback receives a 3-tuple: (key_tuple, metadata, bins)
            # The key_tuple itself is (namespace, set, primary_key)
            (key_tuple, _metadata, _bins) = record
            primary_key = key_tuple[2]  # Extract primary_key from the key_tuple
            if isinstance(primary_key, str) and primary_key.startswith(pattern):
                keys.append(primary_key)

        # Scan the set for keys matching the collection
        _scan_aerospike_set(self._client, self._namespace, self._set, callback)

        # Extract just the key part from compound keys
        result_keys = get_keys_from_compound_keys(compound_keys=keys, collection=collection)

        return result_keys[:limit]

    @override
    async def _delete_store(self) -> bool:
        """Truncate the set (delete all records in the set)."""
        # Aerospike truncate requires a timestamp parameter
        # Using 0 means truncate everything
        _truncate_aerospike_set(self._client, self._namespace, self._set)
        return True
