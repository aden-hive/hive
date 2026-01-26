from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import overload

from key_value.shared.utils.compound import compound_key
from key_value.shared.utils.managed_entry import ManagedEntry
from typing_extensions import override

from key_value.aio.stores.base import BaseContextManagerStore, BaseStore

try:
    from rocksdict import Options, Rdict, WriteBatch
except ImportError as e:
    msg = "RocksDBStore requires py-key-value-aio[rocksdb]"
    raise ImportError(msg) from e


class RocksDBStore(BaseContextManagerStore, BaseStore):
    """A RocksDB-based key-value store."""

    _db: Rdict

    @overload
    def __init__(self, *, db: Rdict, default_collection: str | None = None) -> None:
        """Initialize the RocksDB store.

        Args:
            db: An existing Rdict database instance to use.
            default_collection: The default collection to use if no collection is provided.
        """

    @overload
    def __init__(self, *, path: Path | str, default_collection: str | None = None) -> None:
        """Initialize the RocksDB store.

        Args:
            path: The path to the RocksDB database directory.
            default_collection: The default collection to use if no collection is provided.
        """

    def __init__(
        self,
        *,
        db: Rdict | None = None,
        path: Path | str | None = None,
        default_collection: str | None = None,
    ) -> None:
        """Initialize the RocksDB store.

        Args:
            db: An existing Rdict database instance to use. If provided, the store will NOT
                manage its lifecycle (will not close it). The caller is responsible for managing
                the database's lifecycle.
            path: The path to the RocksDB database directory.
            default_collection: The default collection to use if no collection is provided.
        """
        if db is not None and path is not None:
            msg = "Provide only one of db or path"
            raise ValueError(msg)

        if db is None and path is None:
            msg = "Either db or path must be provided"
            raise ValueError(msg)

        client_provided = db is not None

        if db:
            self._db = db
        elif path:
            path = Path(path)
            path.mkdir(parents=True, exist_ok=True)

            opts = Options()
            opts.create_if_missing(True)

            self._db = Rdict(str(path), options=opts)

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
        )

    @override
    async def _setup(self) -> None:
        """Register database cleanup if we own the database."""
        if not self._client_provided_by_user:
            # Register a callback to close and flush the database
            self._exit_stack.callback(self._close_and_flush)

    def _close_and_flush(self) -> None:
        self._db.flush()
        self._db.close()

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        combo_key: str = compound_key(collection=collection, key=key)

        value: bytes | None = self._db.get(combo_key)

        if value is None:
            return None

        managed_entry_str: str = value.decode("utf-8")
        managed_entry: ManagedEntry = self._serialization_adapter.load_json(json_str=managed_entry_str)

        return managed_entry

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

        self._db[combo_key] = json_value.encode("utf-8")

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

        batch = WriteBatch()
        for key, managed_entry in zip(keys, managed_entries, strict=True):
            combo_key: str = compound_key(collection=collection, key=key)
            json_value: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)
            batch.put(combo_key, json_value.encode("utf-8"))

        self._db.write(batch)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        combo_key: str = compound_key(collection=collection, key=key)

        # Check if key exists before deleting, this is only used for tracking deleted count
        exists = combo_key in self._db

        self._db.delete(combo_key)

        return exists

    @override
    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        if not keys:
            return 0

        # Use WriteBatch for efficient batch deletes
        batch = WriteBatch()
        deleted_count = 0

        for key in keys:
            combo_key: str = compound_key(collection=collection, key=key)

            # Check if key exists before deleting
            if combo_key in self._db:
                deleted_count += 1

            batch.delete(combo_key)

        if deleted_count > 0:
            self._db.write(batch)

        return deleted_count
