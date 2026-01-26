import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, overload

from key_value.shared.errors import DeserializationError
from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.serialization import SerializationAdapter
from typing_extensions import override

from key_value.aio.stores.base import SEED_DATA_TYPE, BaseContextManagerStore, BaseStore

try:
    import duckdb
except ImportError as e:
    msg = "DuckDBStore requires the duckdb extra from py-key-value-aio or py-key-value-sync"
    raise ImportError(msg) from e


class DuckDBSerializationAdapter(SerializationAdapter):
    """Adapter for DuckDB with native JSON storage."""

    def __init__(self) -> None:
        """Initialize the DuckDB adapter."""
        super().__init__()

        self._date_format = "datetime"

    @override
    def prepare_dump(self, data: dict[str, Any]) -> dict[str, Any]:
        """Prepare data for dumping to DuckDB."""
        return data

    @override
    def prepare_load(self, data: dict[str, Any]) -> dict[str, Any]:
        """Prepare data loaded from DuckDB for conversion to ManagedEntry.

        Handles timezone conversion for DuckDB's naive timestamps.
        """
        # DuckDB always returns naive timestamps, but ManagedEntry expects timezone-aware ones
        self._convert_timestamps_to_utc(data)

        return data

    def _convert_timestamps_to_utc(self, data: dict[str, Any]) -> None:
        """Convert naive timestamps to UTC timezone-aware timestamps."""
        created_at = data.get("created_at")
        if created_at is not None and isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                data["created_at"] = created_at.replace(tzinfo=timezone.utc)
            else:
                data["created_at"] = created_at.astimezone(tz=timezone.utc)

        expires_at = data.get("expires_at")
        if expires_at is not None and isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                data["expires_at"] = expires_at.replace(tzinfo=timezone.utc)
            else:
                data["expires_at"] = expires_at.astimezone(tz=timezone.utc)


class DuckDBStore(BaseContextManagerStore, BaseStore):
    """A DuckDB-based key-value store supporting both in-memory and persistent storage.

    DuckDB is an in-process SQL OLAP database that provides excellent performance
    for analytical workloads while supporting standard SQL operations. This store
    can operate in memory-only mode or persist data to disk.

    The store uses native DuckDB types (JSON, TIMESTAMP) to enable efficient SQL queries
    on stored data. Users can query the database directly for analytics or data exploration.

    Values are stored in a JSON column as native dicts, allowing direct SQL queries
    on the stored data for analytics and reporting.
    """

    _connection: duckdb.DuckDBPyConnection
    _adapter: SerializationAdapter
    _table_name: str

    @overload
    def __init__(
        self,
        *,
        connection: duckdb.DuckDBPyConnection,
        table_name: str = "kv_entries",
        default_collection: str | None = None,
        seed: SEED_DATA_TYPE | None = None,
    ) -> None:
        """Initialize the DuckDB store with an existing connection.

        Note: If you provide a connection, the store will NOT manage its lifecycle (will not
        close it). The caller is responsible for managing the connection's lifecycle.

        Args:
            connection: An existing DuckDB connection to use.
            table_name: Name of the table to store key-value entries. Defaults to "kv_entries".
            default_collection: The default collection to use if no collection is provided.
            seed: Optional seed data to pre-populate the store.
        """

    @overload
    def __init__(
        self,
        *,
        database_path: Path | str | None = None,
        table_name: str = "kv_entries",
        default_collection: str | None = None,
        seed: SEED_DATA_TYPE | None = None,
    ) -> None:
        """Initialize the DuckDB store with a database path.

        Args:
            database_path: Path to the database file. If None or ':memory:', uses in-memory database.
            table_name: Name of the table to store key-value entries. Defaults to "kv_entries".
            default_collection: The default collection to use if no collection is provided.
            seed: Optional seed data to pre-populate the store.
        """

    def __init__(
        self,
        *,
        connection: duckdb.DuckDBPyConnection | None = None,
        database_path: Path | str | None = None,
        table_name: str = "kv_entries",
        default_collection: str | None = None,
        seed: SEED_DATA_TYPE | None = None,
    ) -> None:
        """Initialize the DuckDB store.

        Args:
            connection: An existing DuckDB connection to use. If provided, the store will NOT
                manage its lifecycle (will not close it). The caller is responsible for managing
                the connection's lifecycle.
            database_path: Path to the database file. If None or ':memory:', uses in-memory database.
            table_name: Name of the table to store key-value entries. Defaults to "kv_entries".
            default_collection: The default collection to use if no collection is provided.
            seed: Optional seed data to pre-populate the store.
        """
        if connection is not None and database_path is not None:
            msg = "Provide only one of connection or database_path"
            raise ValueError(msg)

        client_provided = connection is not None

        if connection is not None:
            self._connection = connection
        else:
            # Convert Path to string if needed
            if isinstance(database_path, Path):
                database_path = str(database_path)

            # Use in-memory database if no path specified
            if database_path is None or database_path == ":memory:":
                self._connection = duckdb.connect(":memory:")
            else:
                self._connection = duckdb.connect(database=database_path)

        self._adapter = DuckDBSerializationAdapter()

        # Validate table name to prevent SQL injection
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
            msg = "Table name must start with a letter or underscore and contain only letters, digits, or underscores"
            raise ValueError(msg)
        self._table_name = table_name

        super().__init__(
            default_collection=default_collection,
            seed=seed,
            client_provided_by_user=client_provided,
            stable_api=False,
        )

    def _get_create_table_sql(self) -> str:
        """Generate SQL for creating the key-value entries table.

        Returns:
            SQL CREATE TABLE statement.
        """
        return f"""
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                collection VARCHAR NOT NULL,
                key VARCHAR NOT NULL,
                value JSON NOT NULL,
                created_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                version INT NOT NULL,
                PRIMARY KEY (collection, key)
            )
        """

    def _get_create_collection_index_sql(self) -> str:
        """Generate SQL for creating index on collection column.

        Returns:
            SQL CREATE INDEX statement.
        """
        return f"""
            CREATE INDEX IF NOT EXISTS idx_{self._table_name}_collection
            ON {self._table_name}(collection)
        """

    def _get_create_expires_index_sql(self) -> str:
        """Generate SQL for creating index on expires_at column.

        Returns:
            SQL CREATE INDEX statement.
        """
        return f"""
            CREATE INDEX IF NOT EXISTS idx_{self._table_name}_expires_at
            ON {self._table_name}(expires_at)
        """

    def _get_select_sql(self) -> str:
        """Generate SQL for selecting an entry by collection and key.

        Returns:
            SQL SELECT statement with placeholders.
        """
        return f"""
            SELECT value, created_at, expires_at, version
            FROM {self._table_name}
            WHERE collection = ? AND key = ?
        """  # noqa: S608

    def _get_insert_sql(self) -> str:
        """Generate SQL for inserting or replacing an entry.

        Returns:
            SQL INSERT OR REPLACE statement with placeholders.
        """
        return f"""
            INSERT OR REPLACE INTO {self._table_name}
            (collection, key, value, created_at, expires_at, version)
            VALUES (?, ?, ?, ?, ?, ?)
        """  # noqa: S608

    def _get_delete_sql(self) -> str:
        """Generate SQL for deleting an entry by collection and key.

        Returns:
            SQL DELETE statement with RETURNING clause.
        """
        return f"""
            DELETE FROM {self._table_name}
            WHERE collection = ? AND key = ?
            RETURNING key
        """  # noqa: S608

    @override
    async def _setup(self) -> None:
        """Initialize the database schema for key-value storage.

        The schema uses native DuckDB types for efficient querying:
        - value: JSON column storing native dicts for queryability
        - created_at: TIMESTAMP for native datetime operations
        - expires_at: TIMESTAMP for native expiration queries

        This design enables:
        - Direct SQL queries on the database for analytics
        - Efficient expiration cleanup: DELETE FROM table WHERE expires_at < now()
        - Metadata queries without JSON deserialization
        - Native JSON column support for rich querying capabilities
        """
        # Register connection cleanup if we own the connection
        if not self._client_provided_by_user:
            self._exit_stack.callback(self._connection.close)

        # Create the main table for storing key-value entries
        self._connection.execute(self._get_create_table_sql())

        # Create index for efficient collection queries
        self._connection.execute(self._get_create_collection_index_sql())

        # Create index for expiration-based queries
        self._connection.execute(self._get_create_expires_index_sql())

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        """Retrieve a managed entry by key from the specified collection.

        Reconstructs the ManagedEntry from value column and metadata columns
        using the serialization adapter.
        """
        result = self._connection.execute(
            self._get_select_sql(),
            [collection, key],
        ).fetchone()

        if result is None:
            return None

        value, created_at, expires_at, version = result

        # Build document dict for the adapter
        document: dict[str, Any] = {
            "value": value,
            "created_at": created_at,
            "expires_at": expires_at,
            "version": version,
        }

        document = {k: v for k, v in document.items() if v is not None}

        try:
            managed_entry = self._adapter.load_dict(data=document)
        except DeserializationError:
            return None

        return managed_entry

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        """Store a managed entry by key in the specified collection.

        Uses the serialization adapter to convert the ManagedEntry to the
        appropriate storage format.
        """
        # Ensure that the value is serializable to JSON
        _ = managed_entry.value_as_json

        # Use adapter to dump the managed entry to a dict with key and collection
        document = self._adapter.dump_dict(entry=managed_entry, key=key, collection=collection)

        # Insert or replace the entry with metadata in separate columns
        self._connection.execute(
            self._get_insert_sql(),
            [
                collection,
                key,
                document["value"],
                document.get("created_at"),
                document.get("expires_at"),
                document.get("version"),
            ],
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry by key from the specified collection."""
        result = self._connection.execute(
            self._get_delete_sql(),
            [collection, key],
        )

        # Check if any rows were deleted by counting returned rows
        deleted_rows = result.fetchall()
        return len(deleted_rows) > 0
