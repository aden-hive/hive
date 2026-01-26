"""
Base abstract class for managed key-value store implementations.
"""

from abc import ABC, abstractmethod
from asyncio.locks import Lock
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from datetime import datetime
from types import MappingProxyType, TracebackType
from typing import Any, SupportsFloat

from key_value.shared.constants import DEFAULT_COLLECTION_NAME
from key_value.shared.errors import StoreSetupError
from key_value.shared.type_checking.bear_spray import bear_enforce
from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.sanitization import PassthroughStrategy, SanitizationStrategy
from key_value.shared.utils.serialization import BasicSerializationAdapter, SerializationAdapter
from key_value.shared.utils.time_to_live import prepare_entry_timestamps
from typing_extensions import Self, override

from key_value.aio.protocols.key_value import (
    AsyncCullProtocol,
    AsyncDestroyCollectionProtocol,
    AsyncDestroyStoreProtocol,
    AsyncEnumerateCollectionsProtocol,
    AsyncEnumerateKeysProtocol,
    AsyncKeyValueProtocol,
)

SEED_DATA_TYPE = Mapping[str, Mapping[str, Mapping[str, Any]]]
FROZEN_SEED_DATA_TYPE = MappingProxyType[str, MappingProxyType[str, MappingProxyType[str, Any]]]
DEFAULT_SEED_DATA: FROZEN_SEED_DATA_TYPE = MappingProxyType({})


def _seed_to_frozen_seed_data(seed: SEED_DATA_TYPE) -> FROZEN_SEED_DATA_TYPE:
    """Convert mutable seed data to an immutable frozen structure.

    This function converts the nested mapping structure of seed data into immutable MappingProxyType
    objects at all levels. Using immutable structures prevents accidental modification of seed data
    after store initialization and ensures thread-safety.

    Args:
        seed: The mutable seed data mapping: {collection: {key: {field: value}}}.

    Returns:
        An immutable frozen version of the seed data using MappingProxyType.
    """
    return MappingProxyType(
        {collection: MappingProxyType({key: MappingProxyType(value) for key, value in items.items()}) for collection, items in seed.items()}
    )


class BaseStore(AsyncKeyValueProtocol, ABC):
    """An opinionated Abstract base class for managed key-value stores using ManagedEntry objects.

    This class implements all of the methods required for compliance with the KVStore protocol but
    requires subclasses to implement the _get_managed_entry, _put_managed_entry, and _delete_managed_entry methods.

    Subclasses can also override the _get_managed_entries, _put_managed_entries, and _delete_managed_entries methods if desired.

    Subclasses can implement the _setup, which will be called once before the first use of the store, and _setup_collection, which will
    be called once per collection before the first use of a collection.
    """

    _setup_complete: bool
    _setup_lock: Lock

    _setup_collection_locks: defaultdict[str, Lock]
    _setup_collection_complete: defaultdict[str, bool]

    _serialization_adapter: SerializationAdapter
    _key_sanitization_strategy: SanitizationStrategy
    _collection_sanitization_strategy: SanitizationStrategy

    _seed: FROZEN_SEED_DATA_TYPE

    default_collection: str

    def __init__(
        self,
        *,
        serialization_adapter: SerializationAdapter | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        default_collection: str | None = None,
        seed: SEED_DATA_TYPE | None = None,
        stable_api: bool = False,
    ) -> None:
        """Initialize the managed key-value store.

        Args:
            serialization_adapter: The serialization adapter to use for the store.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            default_collection: The default collection to use if no collection is provided.
                Defaults to "default_collection".
            seed: Optional seed data to pre-populate the store. Format: {collection: {key: {field: value, ...}}}.
                Seeding occurs once during store initialization (when the store is first entered or when the
                first operation is performed on the store).
            stable_api: Whether this store implementation has a stable API. If False, a warning will be issued.
                Defaults to False.
        """

        self._setup_complete = False
        self._setup_lock = Lock()
        self._setup_collection_locks = defaultdict(Lock)
        self._setup_collection_complete = defaultdict(bool)

        self._seed = _seed_to_frozen_seed_data(seed=seed or {})

        self.default_collection = default_collection or DEFAULT_COLLECTION_NAME

        self._serialization_adapter = serialization_adapter or BasicSerializationAdapter()

        self._key_sanitization_strategy = key_sanitization_strategy or PassthroughStrategy()
        self._collection_sanitization_strategy = collection_sanitization_strategy or PassthroughStrategy()

        self._stable_api = stable_api

        if not self._stable_api:
            self._warn_about_stability()

        super().__init__()

    async def _setup(self) -> None:
        """Initialize the store (called once before first use)."""

    async def _setup_collection(self, *, collection: str) -> None:
        """Initialize the collection (called once before first use of the collection)."""

    def _sanitize_collection_and_key(self, collection: str, key: str) -> tuple[str, str]:
        return self._sanitize_collection(collection=collection), self._sanitize_key(key=key)

    def _sanitize_collection(self, collection: str) -> str:
        self._collection_sanitization_strategy.validate(value=collection)
        return self._collection_sanitization_strategy.sanitize(value=collection)

    def _sanitize_key(self, key: str) -> str:
        self._key_sanitization_strategy.validate(value=key)
        return self._key_sanitization_strategy.sanitize(value=key)

    async def _seed_store(self) -> None:
        """Seed the store with the data from the seed."""
        for collection, items in self._seed.items():
            await self.setup_collection(collection=collection)
            for key, value in items.items():
                await self.put(key=key, value=dict(value), collection=collection)

    async def setup(self) -> None:
        """Initialize the store if not already initialized.

        This method is called automatically before any store operations and uses a lock to ensure
        thread-safe lazy initialization. It can also be called manually to ensure the store is ready
        before performing operations. The setup process includes calling the `_setup()` hook and
        seeding the store with initial data if provided.

        This method is idempotent - calling it multiple times has no additional effect after the first call.
        """
        if not self._setup_complete:
            async with self._setup_lock:
                if not self._setup_complete:
                    try:
                        await self._setup()
                    except Exception as e:
                        raise StoreSetupError(
                            message=f"Failed to setup key value store: {e}", extra_info={"store": self.__class__.__name__}
                        ) from e

                    self._setup_complete = True

                    await self._seed_store()

    async def setup_collection(self, *, collection: str) -> None:
        """Initialize a specific collection if not already initialized.

        This method is called automatically before any collection-specific operations and uses a per-collection
        lock to ensure thread-safe lazy initialization. It can also be called manually to ensure a collection
        is ready before performing operations on it. The setup process includes calling the `_setup_collection()`
        hook for store-specific collection initialization.

        This method is idempotent - calling it multiple times for the same collection has no additional effect
        after the first call.

        Args:
            collection: The name of the collection to initialize.
        """
        await self.setup()

        if not self._setup_collection_complete[collection]:
            async with self._setup_collection_locks[collection]:
                if not self._setup_collection_complete[collection]:
                    try:
                        await self._setup_collection(collection=collection)
                    except Exception as e:
                        raise StoreSetupError(message=f"Failed to setup collection: {e}", extra_info={"collection": collection}) from e
                    self._setup_collection_complete[collection] = True

    @abstractmethod
    async def _get_managed_entry(self, *, collection: str, key: str) -> ManagedEntry | None:
        """Retrieve a cache entry by key from the specified collection."""

    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        """Retrieve multiple managed entries by key from the specified collection."""

        return [await self._get_managed_entry(collection=collection, key=key) for key in keys]

    @bear_enforce
    @override
    async def get(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a value by key from the specified collection.

        Args:
            collection: The collection to retrieve the value from. If no collection is provided, it will use the default collection.
            key: The key to retrieve the value from.

        Returns:
            The value associated with the key, or None if not found or expired.
        """
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        managed_entry: ManagedEntry | None = await self._get_managed_entry(collection=collection, key=key)

        if not managed_entry:
            return None

        if managed_entry.is_expired:
            return None

        return dict(managed_entry.value)

    @bear_enforce
    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        entries = await self._get_managed_entries(keys=keys, collection=collection)
        return [dict(entry.value) if entry and not entry.is_expired else None for entry in entries]

    @bear_enforce
    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        managed_entry: ManagedEntry | None = await self._get_managed_entry(collection=collection, key=key)

        if not managed_entry or managed_entry.is_expired:
            return (None, None)

        return (dict(managed_entry.value), managed_entry.ttl)

    @bear_enforce
    @override
    async def ttl_many(
        self,
        keys: Sequence[str],
        *,
        collection: str | None = None,
    ) -> list[tuple[dict[str, Any] | None, float | None]]:
        """Retrieve multiple values and TTLs by key from the specified collection.

        Returns a list of tuples of the form (value, ttl_seconds). Missing or expired
        entries are represented as (None, None).
        """
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        entries = await self._get_managed_entries(keys=keys, collection=collection)
        return [(dict(entry.value), entry.ttl) if entry and not entry.is_expired else (None, None) for entry in entries]

    @abstractmethod
    async def _put_managed_entry(
        self,
        *,
        collection: str,
        key: str,
        managed_entry: ManagedEntry,
    ) -> None:
        """Store a managed entry by key in the specified collection."""
        ...

    async def _put_managed_entries(
        self,
        *,
        collection: str,
        keys: Sequence[str],
        managed_entries: Sequence[ManagedEntry],
        ttl: float | None,  # noqa: ARG002
        created_at: datetime,  # noqa: ARG002
        expires_at: datetime | None,  # noqa: ARG002
    ) -> None:
        """Store multiple managed entries by key in the specified collection.

        Args:
            collection: The collection to store entries in
            keys: The keys for the entries
            managed_entries: The managed entries to store
            ttl: The TTL in seconds (None for no expiration)
            created_at: The creation timestamp for all entries
            expires_at: The expiration timestamp for all entries (None if no TTL)
        """
        for key, managed_entry in zip(keys, managed_entries, strict=True):
            await self._put_managed_entry(
                collection=collection,
                key=key,
                managed_entry=managed_entry,
            )

    @bear_enforce
    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        """Store a key-value pair in the specified collection with optional TTL."""
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        created_at, _, expires_at = prepare_entry_timestamps(ttl=ttl)

        managed_entry: ManagedEntry = ManagedEntry(value=value, created_at=created_at, expires_at=expires_at)

        await self._put_managed_entry(
            collection=collection,
            key=key,
            managed_entry=managed_entry,
        )

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        """Store multiple key-value pairs in the specified collection."""

        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        if len(keys) != len(values):
            msg = "put_many called but a different number of keys and values were provided"
            raise ValueError(msg) from None

        created_at, ttl_seconds, expires_at = prepare_entry_timestamps(ttl=ttl)

        managed_entries: list[ManagedEntry] = [ManagedEntry(value=value, created_at=created_at, expires_at=expires_at) for value in values]

        await self._put_managed_entries(
            collection=collection,
            keys=keys,
            managed_entries=managed_entries,
            ttl=ttl_seconds,
            created_at=created_at,
            expires_at=expires_at,
        )

    @abstractmethod
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry by key from the specified collection."""
        ...

    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        """Delete multiple managed entries by key from the specified collection."""

        deleted_count: int = 0

        for key in keys:
            if await self._delete_managed_entry(key=key, collection=collection):
                deleted_count += 1

        return deleted_count

    @bear_enforce
    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        return await self._delete_managed_entry(key=key, collection=collection)

    @bear_enforce
    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        """Delete multiple managed entries by key from the specified collection."""
        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        return await self._delete_managed_entries(keys=keys, collection=collection)

    def _warn_about_stability(self) -> None:
        """Warn about the stability of the store."""
        from warnings import warn

        warn(
            message="A configured store is unstable and may change in a backwards incompatible way. Use at your own risk.",
            category=UserWarning,
            stacklevel=2,
        )


class BaseEnumerateKeysStore(BaseStore, AsyncEnumerateKeysProtocol, ABC):
    """An abstract base class for enumerate key-value stores.

    Subclasses must implement the _get_collection_keys method.
    """

    @override
    async def keys(self, collection: str | None = None, *, limit: int | None = None) -> list[str]:
        """List all keys in the specified collection."""

        collection = collection or self.default_collection
        await self.setup_collection(collection=collection)

        return await self._get_collection_keys(collection=collection, limit=limit)

    @abstractmethod
    async def _get_collection_keys(self, *, collection: str, limit: int | None = None) -> list[str]:
        """List all keys in the specified collection."""


class BaseContextManagerStore(BaseStore, ABC):
    """An abstract base class for context manager stores.

    Stores that accept a client parameter should pass `client_provided_by_user=True` to
    the constructor. This ensures the store does not manage the lifecycle of user-provided
    clients (i.e., does not close them).

    The base class provides an AsyncExitStack that stores can use to register cleanup
    callbacks. Stores should add their cleanup operations to the exit stack as needed.
    The base class handles entering and exiting the exit stack.
    """

    _client_provided_by_user: bool
    _exit_stack: AsyncExitStack
    _exit_stack_entered: bool

    def __init__(self, *, client_provided_by_user: bool = False, **kwargs: Any) -> None:
        """Initialize the context manager store with client ownership configuration.

        Args:
            client_provided_by_user: Whether the client was provided by the user. If True,
                the store will not manage the client's lifecycle (will not close it).
                Defaults to False.
            **kwargs: Additional arguments to pass to the base store constructor.
        """
        self._client_provided_by_user = client_provided_by_user
        self._exit_stack = AsyncExitStack()
        self._exit_stack_entered = False
        super().__init__(**kwargs)

    async def _ensure_exit_stack_entered(self) -> None:
        """Ensure the exit stack has been entered."""
        if not self._exit_stack_entered:
            await self._exit_stack.__aenter__()
            self._exit_stack_entered = True

    async def __aenter__(self) -> Self:
        # Enter the exit stack
        await self._ensure_exit_stack_entered()
        await self.setup()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> bool | None:
        # Close the exit stack, which handles all cleanup
        if self._exit_stack_entered:
            result = await self._exit_stack.__aexit__(exc_type, exc_value, traceback)
            self._exit_stack_entered = False

            return result
        return None

    async def close(self) -> None:
        # Close the exit stack if it has been entered
        if self._exit_stack_entered:
            await self._exit_stack.aclose()
            self._exit_stack_entered = False

    async def setup(self) -> None:
        """Initialize the store if not already initialized.

        This override ensures the exit stack is entered before the store's _setup()
        method is called, allowing stores to register cleanup callbacks during setup.
        """
        # Ensure exit stack is entered
        await self._ensure_exit_stack_entered()
        # Call parent setup
        await super().setup()


class BaseEnumerateCollectionsStore(BaseStore, AsyncEnumerateCollectionsProtocol, ABC):
    """An abstract base class for enumerate collections stores.

    Subclasses must implement the _get_collection_names method.
    """

    @override
    async def collections(self, *, limit: int | None = None) -> list[str]:
        """List all available collection names (may include empty collections)."""
        await self.setup()

        return await self._get_collection_names(limit=limit)

    @abstractmethod
    async def _get_collection_names(self, *, limit: int | None = None) -> list[str]:
        """List all available collection names (may include empty collections)."""


class BaseDestroyStore(BaseStore, AsyncDestroyStoreProtocol, ABC):
    """An abstract base class for destroyable stores.

    Subclasses must implement the _delete_store method.
    """

    @override
    async def destroy(self) -> bool:
        """Destroy the store."""
        await self.setup()

        return await self._delete_store()

    @abstractmethod
    async def _delete_store(self) -> bool:
        """Delete the store."""
        ...


class BaseDestroyCollectionStore(BaseStore, AsyncDestroyCollectionProtocol, ABC):
    """An abstract base class for destroyable collections.

    Subclasses must implement the _delete_collection method.
    """

    @override
    async def destroy_collection(self, collection: str) -> bool:
        """Destroy the collection."""
        await self.setup()

        return await self._delete_collection(collection=collection)

    @abstractmethod
    async def _delete_collection(self, *, collection: str) -> bool:
        """Delete the collection."""
        ...


class BaseCullStore(BaseStore, AsyncCullProtocol, ABC):
    """An abstract base class for cullable stores.

    Subclasses must implement the _cull method.
    """

    @override
    async def cull(self) -> None:
        """Cull the store."""
        await self.setup()

        return await self._cull()

    @abstractmethod
    async def _cull(self) -> None:
        """Cull the store."""
        ...
