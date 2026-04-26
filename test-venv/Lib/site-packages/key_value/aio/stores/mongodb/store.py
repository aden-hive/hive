from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, overload

from bson.errors import InvalidDocument
from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.sanitization import HybridSanitizationStrategy, SanitizationStrategy
from key_value.aio._utils.sanitize import ALPHANUMERIC_CHARACTERS
from key_value.aio._utils.serialization import SerializationAdapter
from key_value.aio.errors import DeserializationError, SerializationError
from key_value.aio.stores.base import BaseContextManagerStore, BaseDestroyCollectionStore, BaseStore

try:
    from pymongo import AsyncMongoClient, UpdateOne
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.results import BulkWriteResult, DeleteResult
except ImportError as e:
    msg = "MongoDBStore requires py-key-value-aio[mongodb]"
    raise ImportError(msg) from e


# Module-level helper functions for MongoDB client operations


def _create_mongodb_client(url: str | None = None) -> AsyncMongoClient[dict[str, Any]]:
    """Create a MongoDB async client.

    Args:
        url: Optional MongoDB connection URL. If not provided, uses localhost.

    Returns:
        An AsyncMongoClient instance.
    """
    if url:
        return AsyncMongoClient(url)
    return AsyncMongoClient()


async def _mongodb_bulk_write(
    collection: AsyncCollection[dict[str, Any]],
    operations: list[UpdateOne],
) -> BulkWriteResult:
    """Execute a bulk write operation on a MongoDB collection.

    Args:
        collection: The MongoDB collection to write to.
        operations: List of UpdateOne operations to execute.

    Returns:
        The BulkWriteResult from the operation.
    """
    return await collection.bulk_write(operations)


async def _mongodb_drop_database(client: AsyncMongoClient[dict[str, Any]], db_name: str) -> None:  # pyright: ignore[reportUnusedFunction] - Used by tests
    """Drop a MongoDB database.

    Args:
        client: The MongoDB client.
        db_name: The name of the database to drop.
    """
    _ = await client.drop_database(name_or_database=db_name)


DEFAULT_DB = "kv-store-adapter"
DEFAULT_COLLECTION = "kv"

DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000

# MongoDB collection name length limit
# https://www.mongodb.com/docs/manual/reference/limits/
# For unsharded collections and views, the namespace length limit is 255 bytes.
# For sharded collections, the namespace length limit is 235 bytes.
# So limit the collection name to 200 bytes
MAX_COLLECTION_LENGTH = 200
COLLECTION_ALLOWED_CHARACTERS = ALPHANUMERIC_CHARACTERS + "_"


class MongoDBSerializationAdapter(SerializationAdapter):
    """Adapter for MongoDB with native BSON storage."""

    def __init__(self) -> None:
        """Initialize the MongoDB adapter."""
        super().__init__()

        self._date_format = "datetime"
        self._value_format = "dict"

    @override
    def prepare_dump(self, data: dict[str, Any]) -> dict[str, Any]:
        value = data.pop("value")

        data["value"] = {"object": value}

        return data

    @override
    def prepare_load(self, data: dict[str, Any]) -> dict[str, Any]:
        value = data.pop("value")

        if "object" in value:
            data["value"] = value["object"]
        else:
            msg = "Value field not found in MongoDB document"
            raise DeserializationError(message=msg)

        if date_created := data.get("created_at"):
            if not isinstance(date_created, datetime):
                msg = "Expected `created_at` field to be a datetime"
                raise DeserializationError(message=msg)
            data["created_at"] = date_created.replace(tzinfo=timezone.utc)
        if date_expires := data.get("expires_at"):
            if not isinstance(date_expires, datetime):
                msg = "Expected `expires_at` field to be a datetime"
                raise DeserializationError(message=msg)
            data["expires_at"] = date_expires.replace(tzinfo=timezone.utc)

        return data


class MongoDBV1CollectionSanitizationStrategy(HybridSanitizationStrategy):
    def __init__(self) -> None:
        super().__init__(
            replacement_character="_",
            max_length=MAX_COLLECTION_LENGTH,
            allowed_characters=COLLECTION_ALLOWED_CHARACTERS,
        )


class MongoDBStore(BaseDestroyCollectionStore, BaseContextManagerStore, BaseStore):
    """MongoDB-based key-value store using pymongo.

    Stores collections as MongoDB collections and stores values in document fields.

    By default, collections are not sanitized. This means that there are character and length restrictions on
    collection names that may cause errors when trying to get and put entries.

    To avoid issues, you may want to consider leveraging the `MongoDBV1CollectionSanitizationStrategy` strategy.
    """

    _client: AsyncMongoClient[dict[str, Any]]
    _db: AsyncDatabase[dict[str, Any]]
    _collections_by_name: dict[str, AsyncCollection[dict[str, Any]]]
    _adapter: SerializationAdapter
    _auto_create: bool

    @overload
    def __init__(
        self,
        *,
        client: AsyncMongoClient[dict[str, Any]],
        db_name: str | None = None,
        coll_name: str | None = None,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the MongoDB store.

        Args:
            client: The MongoDB client to use.
            db_name: The name of the MongoDB database.
            coll_name: The name of the MongoDB collection.
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create collections if they don't exist. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        url: str,
        db_name: str | None = None,
        coll_name: str | None = None,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the MongoDB store.

        Args:
            url: The url of the MongoDB cluster.
            db_name: The name of the MongoDB database.
            coll_name: The name of the MongoDB collection.
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create collections if they don't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        client: AsyncMongoClient[dict[str, Any]] | None = None,
        url: str | None = None,
        db_name: str | None = None,
        coll_name: str | None = None,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the MongoDB store.

        Values are stored as native BSON dictionaries for better query support and performance.

        Args:
            client: The MongoDB client to use (mutually exclusive with url). If provided, the store
                will not manage the client's lifecycle (will not enter/exit its context manager or
                close it). The caller is responsible for managing the client's lifecycle.
            url: The url of the MongoDB cluster (mutually exclusive with client).
            db_name: The name of the MongoDB database.
            coll_name: The name of the MongoDB collection.
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create collections if they don't exist. Defaults to True.
                When False, raises ValueError if a collection doesn't exist.
        """

        client_provided = client is not None

        if client:
            self._client = client
        else:
            self._client = _create_mongodb_client(url=url)

        db_name = db_name or DEFAULT_DB
        coll_name = coll_name or DEFAULT_COLLECTION

        self._db = self._client[db_name]
        self._collections_by_name = {}
        self._adapter = MongoDBSerializationAdapter()
        self._auto_create = auto_create

        super().__init__(
            default_collection=default_collection,
            collection_sanitization_strategy=collection_sanitization_strategy,
            client_provided_by_user=client_provided,
        )

    @override
    async def _setup(self) -> None:
        """Register client cleanup if we own the client."""
        if not self._client_provided_by_user:
            await self._exit_stack.enter_async_context(self._client)

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        # Ensure index on the unique combo key and supporting queries
        sanitized_collection = self._sanitize_collection(collection=collection)

        collection_filter: dict[str, str] = {"name": sanitized_collection}
        matching_collections: list[str] = await self._db.list_collection_names(filter=collection_filter)

        if matching_collections:
            self._collections_by_name[collection] = self._db[sanitized_collection]
            return

        if not self._auto_create:
            msg = f"Collection '{sanitized_collection}' does not exist. Either create the collection manually or set auto_create=True."
            raise ValueError(msg)

        new_collection: AsyncCollection[dict[str, Any]] = await self._db.create_collection(name=sanitized_collection)

        # Index for efficient key lookups
        _ = await new_collection.create_index(keys="key")

        # TTL index for automatic expiration of entries when expires_at is reached
        _ = await new_collection.create_index(keys="expires_at", expireAfterSeconds=0)

        self._collections_by_name[collection] = new_collection

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        if doc := await self._collections_by_name[collection].find_one(filter={"key": key}):
            try:
                return self._adapter.load_dict(data=doc)
            except DeserializationError:
                return None

        return None

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        if not keys:
            return []

        # Use find with $in operator to get multiple documents at once
        cursor = self._collections_by_name[collection].find(filter={"key": {"$in": keys}})

        managed_entries_by_key: dict[str, ManagedEntry | None] = dict.fromkeys(keys)

        async for doc in cursor:
            if key := doc.get("key"):
                try:
                    managed_entries_by_key[key] = self._adapter.load_dict(data=doc)
                except DeserializationError:
                    managed_entries_by_key[key] = None

        return [managed_entries_by_key[key] for key in keys]

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        mongo_doc = self._adapter.dump_dict(entry=managed_entry, key=key, collection=collection)

        try:
            # Ensure that the value is serializable to JSON
            _ = managed_entry.value_as_json
            _ = await self._collections_by_name[collection].update_one(
                filter={"key": key},
                update={
                    "$set": {
                        "key": key,
                        **mongo_doc,
                    }
                },
                upsert=True,
            )
        except InvalidDocument as e:
            msg = f"Failed to update MongoDB document: {e}"
            raise SerializationError(message=msg) from e

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

        operations: list[UpdateOne] = []
        for key, managed_entry in zip(keys, managed_entries, strict=True):
            mongo_doc = self._adapter.dump_dict(entry=managed_entry, key=key, collection=collection)

            operations.append(
                UpdateOne(
                    filter={"key": key},
                    update={
                        "$set": {
                            "collection": collection,
                            "key": key,
                            **mongo_doc,
                        }
                    },
                    upsert=True,
                )
            )

        _ = await _mongodb_bulk_write(collection=self._collections_by_name[collection], operations=operations)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        result: DeleteResult = await self._collections_by_name[collection].delete_one(filter={"key": key})
        return bool(result.deleted_count)

    @override
    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        if not keys:
            return 0

        result: DeleteResult = await self._collections_by_name[collection].delete_many(filter={"key": {"$in": keys}})

        return result.deleted_count

    @override
    async def _delete_collection(self, *, collection: str) -> bool:
        collection_name = self._collections_by_name[collection].name

        _ = await self._db.drop_collection(name_or_collection=collection_name)

        self._collections_by_name.pop(collection, None)

        return True

    # No need to override _close - the exit stack handles all cleanup automatically
