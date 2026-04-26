"""PostgreSQL-based key-value store using asyncpg.

Note: SQL queries in this module use f-strings for table names, which triggers S608 warnings.
This is safe because table names are validated in __init__ to be alphanumeric plus underscores.
"""

# ruff: noqa: S608

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry, dump_to_json, load_from_json
from key_value.aio.stores.base import BaseContextManagerStore, BaseDestroyCollectionStore, BaseEnumerateCollectionsStore, BaseStore

try:
    import asyncpg
except ImportError as e:
    msg = "PostgreSQLStore requires py-key-value-aio[postgresql]"
    raise ImportError(msg) from e


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "postgres"
DEFAULT_TABLE = "kv_store"

DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000

# PostgreSQL table name length limit is 63 characters
POSTGRES_MAX_IDENTIFIER_LEN = 63


def _validate_table_name(table_name: str) -> None:
    """Validate a PostgreSQL table name.

    Ensures the table name:
    - Contains only alphanumeric characters and underscores
    - Does not start with a digit
    - Does not exceed PostgreSQL's 63-character identifier limit

    Args:
        table_name: The table name to validate.

    Raises:
        ValueError: If the table name is invalid.
    """
    if not table_name.replace("_", "").isalnum():
        msg = f"Table name must be alphanumeric (with underscores): {table_name}"
        raise ValueError(msg)
    if table_name[0].isdigit():
        msg = f"Table name must not start with a digit: {table_name}"
        raise ValueError(msg)
    if len(table_name) > POSTGRES_MAX_IDENTIFIER_LEN:
        msg = f"Table name too long (>{POSTGRES_MAX_IDENTIFIER_LEN}): {table_name}"
        raise ValueError(msg)


# Private helper functions to encapsulate asyncpg pool creation with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


async def _create_postgresql_pool_from_url(url: str) -> asyncpg.Pool:
    """Create an asyncpg pool from a connection URL."""
    return await asyncpg.create_pool(url)  # pyright: ignore[reportUnknownMemberType]


async def _create_postgresql_pool(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    database: str = DEFAULT_DATABASE,
    user: str | None = None,
    password: str | None = None,
) -> asyncpg.Pool:
    """Create an asyncpg pool from connection parameters."""
    return await asyncpg.create_pool(  # pyright: ignore[reportUnknownMemberType]
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )


# Pool operation helpers with type ignores centralized here
async def _postgresql_fetchval(
    pool: asyncpg.Pool,
    query: str,
    *args: object,
) -> object:
    """Fetch a single value from the pool."""
    return await pool.fetchval(query, *args)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def _postgresql_execute(
    pool: asyncpg.Pool,
    query: str,
    *args: object,
) -> str:
    """Execute a query on the pool."""
    return await pool.execute(query, *args)  # pyright: ignore[reportUnknownMemberType]


async def _postgresql_fetchrow(
    pool: asyncpg.Pool,
    query: str,
    *args: object,
) -> asyncpg.Record | None:
    """Fetch a single row from the pool."""
    return await pool.fetchrow(query, *args)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def _postgresql_fetch(
    pool: asyncpg.Pool,
    query: str,
    *args: object,
) -> list[asyncpg.Record]:
    """Fetch multiple rows from the pool."""
    return await pool.fetch(query, *args)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def _postgresql_pool_close_callback(
    pool: asyncpg.Pool,
) -> Callable[[], Awaitable[None]]:
    """Get the pool close callback for the exit stack."""
    return pool.close


def _postgresql_row_get_str(row: asyncpg.Record, key: str) -> str:
    """Get a string value from a PostgreSQL row."""
    return row[key]


def _postgresql_row_get_datetime(row: asyncpg.Record, key: str) -> datetime | None:
    """Get a datetime value from a PostgreSQL row."""
    return row[key]


class PostgreSQLStore(BaseEnumerateCollectionsStore, BaseDestroyCollectionStore, BaseContextManagerStore, BaseStore):
    """PostgreSQL-based key-value store using asyncpg.

    This store uses a single shared table with columns for collection, key, value (JSONB), and metadata.
    Collections are stored as values in the collection column, not as separate tables or SQL identifiers,
    so there are no character restrictions on collection names.

    Example:
        Basic usage with default connection:
        >>> store = PostgreSQLStore()
        >>> async with store:
        ...     await store.put("user_1", {"name": "Alice"}, collection="users")
        ...     user = await store.get("user_1", collection="users")

        Using a connection URL:
        >>> store = PostgreSQLStore(url="postgresql://user:pass@localhost/mydb")
        >>> async with store:
        ...     await store.put("key", {"data": "value"})

        Using custom connection parameters:
        >>> store = PostgreSQLStore(
        ...     host="db.example.com",
        ...     port=5432,
        ...     database="myapp",
        ...     user="myuser",
        ...     password="mypass"
        ... )
    """

    _pool: asyncpg.Pool | None
    _url: str | None
    _host: str
    _port: int
    _database: str
    _user: str | None
    _password: str | None
    _table_name: str
    _auto_create: bool

    @overload
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        table_name: str | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the PostgreSQL store with an existing connection pool.

        Args:
            pool: An existing asyncpg connection pool to use.
            table_name: The name of the table to use for storage (default: kv_store).
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        url: str,
        table_name: str | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the PostgreSQL store with a connection URL.

        Args:
            url: PostgreSQL connection URL (e.g., postgresql://user:pass@localhost/dbname).
            table_name: The name of the table to use for storage (default: kv_store).
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        database: str = DEFAULT_DATABASE,
        user: str | None = None,
        password: str | None = None,
        table_name: str | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the PostgreSQL store with connection parameters.

        Args:
            host: PostgreSQL server host (default: localhost).
            port: PostgreSQL server port (default: 5432).
            database: Database name (default: postgres).
            user: Database user (default: current user).
            password: Database password (default: None).
            table_name: The name of the table to use for storage (default: kv_store).
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool | None = None,
        url: str | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        database: str = DEFAULT_DATABASE,
        user: str | None = None,
        password: str | None = None,
        table_name: str | None = None,
        default_collection: str | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the PostgreSQL store.

        Args:
            pool: An existing asyncpg connection pool to use.
            url: PostgreSQL connection URL (e.g., postgresql://user:pass@localhost/dbname).
            host: PostgreSQL server host (default: localhost).
            port: PostgreSQL server port (default: 5432).
            database: Database name (default: postgres).
            user: Database user (default: current user).
            password: Database password (default: None).
            table_name: The name of the table to use for storage (default: kv_store).
            default_collection: The default collection to use if no collection is provided.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
                When False, raises ValueError if the table doesn't exist.
        """
        pool_provided = pool is not None

        self._pool = pool
        self._url = url
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._auto_create = auto_create

        # Validate table name to prevent SQL injection and invalid identifiers
        table_name = table_name or DEFAULT_TABLE
        _validate_table_name(table_name)
        self._table_name = table_name

        super().__init__(default_collection=default_collection, client_provided_by_user=pool_provided)

    @property
    def _initialized_pool(self) -> asyncpg.Pool:
        """Get the initialized connection pool.

        Returns:
            The connection pool.

        Raises:
            RuntimeError: If the pool has not been initialized (setup() not called).
        """
        if self._pool is None:
            msg = "Pool not initialized. Did you forget to use the context manager or call setup()?"
            raise RuntimeError(msg)
        return self._pool

    async def _create_pool(self) -> asyncpg.Pool:
        """Create a new connection pool.

        Returns:
            The newly created connection pool.
        """
        if self._url:
            return await _create_postgresql_pool_from_url(self._url)
        return await _create_postgresql_pool(
            host=self._host,
            port=self._port,
            database=self._database,
            user=self._user,
            password=self._password,
        )

    @override
    async def _setup(self) -> None:
        """Set up the connection pool, database table and indexes.

        This is called once when the store is first used (protected by the base class's setup lock).
        The pool is created here if not provided by the user, and cleanup is registered with the
        exit stack. Since all collections share the same table, we only need to set up the schema once.
        """
        # Create pool if not provided by user
        if self._pool is None:
            self._pool = await self._create_pool()

        # Register pool cleanup if we own it (created it ourselves)
        if not self._client_provided_by_user:
            self._exit_stack.push_async_callback(_postgresql_pool_close_callback(self._pool))

        pool = self._pool

        # Check if table exists
        table_exists_sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = $1
            )
        """
        table_exists = await _postgresql_fetchval(pool, table_exists_sql, self._table_name)

        if not table_exists:
            if not self._auto_create:
                msg = f"Table '{self._table_name}' does not exist. Either create the table manually or set auto_create=True."
                raise ValueError(msg)

            # Create the main table
            table_sql = (
                f"CREATE TABLE IF NOT EXISTS {self._table_name} ("
                "collection TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "value JSONB NOT NULL, "
                "ttl DOUBLE PRECISION, "
                "created_at TIMESTAMPTZ, "
                "expires_at TIMESTAMPTZ, "
                "PRIMARY KEY (collection, key))"
            )

            # Create index on expires_at for efficient TTL queries
            # Ensure index name <= 63 chars (PostgreSQL identifier limit)
            index_name = f"idx_{self._table_name}_expires_at"
            if len(index_name) > POSTGRES_MAX_IDENTIFIER_LEN:
                import hashlib

                index_name = "idx_" + hashlib.sha256(self._table_name.encode()).hexdigest()[:16] + "_exp"

            index_sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {self._table_name}(expires_at) WHERE expires_at IS NOT NULL"

            await _postgresql_execute(pool, table_sql)
            await _postgresql_execute(pool, index_sql)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        """Retrieve a managed entry by key from the specified collection.

        Args:
            key: The key to retrieve.
            collection: The collection to retrieve from.

        Returns:
            The managed entry if found and not expired, None otherwise.
        """
        pool = self._initialized_pool

        row = await _postgresql_fetchrow(
            pool,
            f"SELECT value, ttl, created_at, expires_at FROM {self._table_name} WHERE collection = $1 AND key = $2",
            collection,
            key,
        )

        if row is None:
            return None

        # Parse the managed entry - asyncpg returns JSONB as JSON strings by default
        value_data = _postgresql_row_get_str(row, "value")
        value = load_from_json(value_data)

        return ManagedEntry(
            value=value,
            created_at=_postgresql_row_get_datetime(row, "created_at"),
            expires_at=_postgresql_row_get_datetime(row, "expires_at"),
        )

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        """Store a managed entry by key in the specified collection.

        Args:
            key: The key to store.
            collection: The collection to store in.
            managed_entry: The managed entry to store.
        """
        pool = self._initialized_pool

        # Serialize value to JSON string for JSONB column
        value_json = dump_to_json(managed_entry.value_as_dict)

        upsert_sql = (
            f"INSERT INTO {self._table_name} "
            "(collection, key, value, ttl, created_at, expires_at) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (collection, key) "
            "DO UPDATE SET value = EXCLUDED.value, ttl = EXCLUDED.ttl, expires_at = EXCLUDED.expires_at"
        )
        await _postgresql_execute(
            pool,
            upsert_sql,
            collection,
            key,
            value_json,
            managed_entry.ttl,
            managed_entry.created_at,
            managed_entry.expires_at,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry by key from the specified collection.

        Args:
            key: The key to delete.
            collection: The collection to delete from.

        Returns:
            True if the entry was deleted, False if it didn't exist.
        """
        pool = self._initialized_pool

        result = await _postgresql_execute(
            pool,
            f"DELETE FROM {self._table_name} WHERE collection = $1 AND key = $2",
            collection,
            key,
        )
        # PostgreSQL execute returns a string like "DELETE N" where N is the number of rows deleted
        return result.split()[-1] != "0"

    @override
    async def _get_collection_names(self, *, limit: int | None = None) -> list[str]:
        """List all collection names.

        Args:
            limit: Maximum number of collection names to return.

        Returns:
            A list of collection names.
        """
        if limit is None or limit <= 0:
            limit = DEFAULT_PAGE_SIZE
        limit = min(limit, PAGE_LIMIT)

        pool = self._initialized_pool

        rows = await _postgresql_fetch(
            pool,
            f"SELECT DISTINCT collection FROM {self._table_name} ORDER BY collection LIMIT $1",
            limit,
        )

        return [_postgresql_row_get_str(row, "collection") for row in rows]

    @override
    async def _delete_collection(self, *, collection: str) -> bool:
        """Delete all entries in a collection.

        Args:
            collection: The collection to delete.

        Returns:
            True if any entries were deleted, False otherwise.
        """
        pool = self._initialized_pool

        result = await _postgresql_execute(
            pool,
            f"DELETE FROM {self._table_name} WHERE collection = $1",
            collection,
        )
        # Return True if any rows were deleted
        return result.split()[-1] != "0"
