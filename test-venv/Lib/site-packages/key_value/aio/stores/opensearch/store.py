import logging
from collections.abc import Sequence
from typing import Any, overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.sanitization import (
    AlwaysHashStrategy,
    HashFragmentMode,
    HybridSanitizationStrategy,
    SanitizationStrategy,
)
from key_value.aio._utils.sanitize import (
    ALPHANUMERIC_CHARACTERS,
    LOWERCASE_ALPHABET,
    NUMBERS,
    UPPERCASE_ALPHABET,
)
from key_value.aio._utils.serialization import SerializationAdapter
from key_value.aio._utils.time_to_live import now_as_epoch
from key_value.aio.errors import DeserializationError, SerializationError
from key_value.aio.stores.base import (
    BaseContextManagerStore,
    BaseCullStore,
    BaseDestroyCollectionStore,
    BaseEnumerateCollectionsStore,
    BaseEnumerateKeysStore,
    BaseStore,
)
from key_value.aio.stores.opensearch.utils import LessCapableJsonSerializer

try:
    from opensearchpy import AsyncOpenSearch
    from opensearchpy.exceptions import NotFoundError, RequestError
    from opensearchpy.exceptions import SerializationError as OpenSearchSerializationError

    from key_value.aio.stores.opensearch.utils import (
        get_aggregations_from_body,
        get_body_from_response,
        get_first_value_from_field_in_hit,
        get_hits_from_response,
        get_source_from_body,
    )
except ImportError as e:
    msg = "OpenSearchStore requires opensearch-py[async]>=2.0.0. Install with: pip install 'py-key-value-aio[opensearch]'"
    raise ImportError(msg) from e


logger = logging.getLogger(__name__)


# Private helper functions to encapsulate OpenSearch client operations with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


async def _opensearch_index(
    client: AsyncOpenSearch,
    index: str,
    document_id: str,
    body: dict[str, Any],
    *,
    refresh: bool = True,
) -> object:
    """Index a document in OpenSearch."""
    return await client.index(
        index=index,
        id=document_id,
        body=body,
        params={"refresh": "true"} if refresh else {},
    )


def _get_aggregation_buckets(aggregations: dict[str, Any], agg_name: str) -> list[Any]:
    """Get buckets from an aggregation result."""
    return aggregations[agg_name]["buckets"]


def _get_bucket_key(bucket: Any) -> str:
    """Get the key from an aggregation bucket."""
    return bucket["key"]


DEFAULT_INDEX_PREFIX = "opensearch_kv_store"

DEFAULT_MAPPING = {
    "properties": {
        "created_at": {
            "type": "date",
        },
        "expires_at": {
            "type": "date",
        },
        "collection": {
            "type": "keyword",
        },
        "key": {
            "type": "keyword",
        },
        "version": {
            "type": "integer",
        },
        "value": {
            "properties": {
                "flat": {
                    "type": "flat_object",
                },
            },
        },
    },
}

DEFAULT_PAGE_SIZE = 10000
PAGE_LIMIT = 10000

MAX_KEY_LENGTH = 256
ALLOWED_KEY_CHARACTERS: str = ALPHANUMERIC_CHARACTERS

MAX_INDEX_LENGTH = 200
ALLOWED_INDEX_CHARACTERS: str = LOWERCASE_ALPHABET + NUMBERS + "_" + "-" + "."


class OpenSearchSerializationAdapter(SerializationAdapter):
    """Adapter for OpenSearch."""

    def __init__(self) -> None:
        """Initialize the OpenSearch adapter"""
        super().__init__()

        self._date_format = "isoformat"
        self._value_format = "dict"

    @override
    def prepare_dump(self, data: dict[str, Any]) -> dict[str, Any]:
        value = data.pop("value")

        data["value"] = {
            "flat": value,
        }

        return data

    @override
    def prepare_load(self, data: dict[str, Any]) -> dict[str, Any]:
        data["value"] = data.pop("value").get("flat")

        return data


class OpenSearchV1KeySanitizationStrategy(AlwaysHashStrategy):
    def __init__(self) -> None:
        super().__init__(
            hash_length=64,
        )


class OpenSearchV1CollectionSanitizationStrategy(HybridSanitizationStrategy):
    def __init__(self) -> None:
        super().__init__(
            replacement_character="_",
            max_length=MAX_INDEX_LENGTH,
            allowed_characters=UPPERCASE_ALPHABET + ALLOWED_INDEX_CHARACTERS,
            hash_fragment_mode=HashFragmentMode.ALWAYS,
        )


class OpenSearchStore(
    BaseEnumerateCollectionsStore, BaseEnumerateKeysStore, BaseDestroyCollectionStore, BaseCullStore, BaseContextManagerStore, BaseStore
):
    """An OpenSearch-based store.

    Stores collections in their own indices and stores values in flat_object fields.

    This store has specific restrictions on what is allowed in keys and collections. Keys and collections are not sanitized
    by default which may result in errors when using the store.

    To avoid issues, you may want to consider leveraging the `OpenSearchV1KeySanitizationStrategy` and
    `OpenSearchV1CollectionSanitizationStrategy` strategies.

    The `auto_create` parameter controls whether indices are automatically created. When set to False, indices must be
    created manually before use, otherwise ValueError will be raised.
    """

    _client: AsyncOpenSearch

    _index_prefix: str

    _default_collection: str | None

    _serializer: SerializationAdapter

    _key_sanitization_strategy: SanitizationStrategy
    _collection_sanitization_strategy: SanitizationStrategy
    _auto_create: bool

    @overload
    def __init__(
        self,
        *,
        opensearch_client: AsyncOpenSearch,
        index_prefix: str,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the opensearch store.

        Args:
            opensearch_client: The opensearch client to use. If provided, the store will not
                manage the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            index_prefix: The index prefix to use. Collections will be prefixed with this prefix.
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create indices if they don't exist. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        index_prefix: str,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the opensearch store.

        Args:
            url: The url of the opensearch cluster.
            api_key: The api key to use.
            index_prefix: The index prefix to use. Collections will be prefixed with this prefix.
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create indices if they don't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        opensearch_client: AsyncOpenSearch | None = None,
        url: str | None = None,
        api_key: str | None = None,
        index_prefix: str,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the opensearch store.

        Args:
            opensearch_client: The opensearch client to use. If provided, the store will not
                manage the client's lifecycle (will not close it). The caller is responsible for
                managing the client's lifecycle.
            url: The url of the opensearch cluster.
            api_key: The api key to use.
            index_prefix: The index prefix to use. Collections will be prefixed with this prefix.
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create indices if they don't exist. Defaults to True.
                When False, raises ValueError if an index doesn't exist.
        """
        if opensearch_client is None and url is None:
            msg = "Either opensearch_client or url must be provided"
            raise ValueError(msg)

        client_provided = opensearch_client is not None

        if opensearch_client:
            self._client = opensearch_client
        elif url:
            client_kwargs: dict[str, Any] = {
                "hosts": [url],
                "http_compress": True,
                "timeout": 10,
                "max_retries": 3,
                "retry_on_timeout": True,
            }
            if api_key:
                client_kwargs["api_key"] = api_key

            self._client = AsyncOpenSearch(**client_kwargs)

        LessCapableJsonSerializer.install_serializer(client=self._client)

        self._index_prefix = index_prefix.lower()
        self._auto_create = auto_create

        self._serializer = OpenSearchSerializationAdapter()

        super().__init__(
            default_collection=default_collection,
            collection_sanitization_strategy=collection_sanitization_strategy,
            key_sanitization_strategy=key_sanitization_strategy,
            client_provided_by_user=client_provided,
        )

    @override
    async def _setup(self) -> None:
        # Register client cleanup if we own the client
        if not self._client_provided_by_user:
            self._exit_stack.push_async_callback(self._client.close)

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        index_name = self._get_index_name(collection=collection)

        if await self._client.indices.exists(index=index_name):
            return

        if not self._auto_create:
            msg = f"Index '{index_name}' does not exist. Either create the index manually or set auto_create=True."
            raise ValueError(msg)

        try:
            _ = await self._client.indices.create(index=index_name, body={"mappings": DEFAULT_MAPPING, "settings": {}})
        except RequestError as e:
            if "resource_already_exists_exception" in str(e).lower():
                return
            raise

    def _get_index_name(self, collection: str) -> str:
        # The Sanitization Strategy ensures that we do not have conflicts between upper and lower case
        # but it does not lowercase the collection name, so we do that here, which conveniently also
        # prevents errors when using PassthroughStrategy.
        return (self._index_prefix + "-" + self._sanitize_collection(collection=collection)).lower()

    def _get_document_id(self, key: str) -> str:
        return self._sanitize_key(key=key)

    def _get_destination(self, *, collection: str, key: str) -> tuple[str, str]:
        index_name: str = self._get_index_name(collection=collection)
        document_id: str = self._get_document_id(key=key)

        return index_name, document_id

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        index_name, document_id = self._get_destination(collection=collection, key=key)

        try:
            opensearch_response = await self._client.get(index=index_name, id=document_id)
        except NotFoundError:
            # Document not found is not an error for get operations
            return None

        body: dict[str, Any] = get_body_from_response(response=opensearch_response)

        if not (source := get_source_from_body(body=body)):
            return None

        try:
            return self._serializer.load_dict(data=source)
        except DeserializationError:
            return None

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        if not keys:
            return []

        # Use mget for efficient batch retrieval
        index_name = self._get_index_name(collection=collection)
        document_ids = [self._get_document_id(key=key) for key in keys]
        docs = [{"_id": document_id} for document_id in document_ids]

        opensearch_response = await self._client.mget(index=index_name, body={"docs": docs})

        body: dict[str, Any] = get_body_from_response(response=opensearch_response)
        docs_result = body.get("docs", [])

        entries_by_id: dict[str, ManagedEntry | None] = {}
        for doc in docs_result:
            if not (doc_id := doc.get("_id")):
                continue

            if "found" not in doc or not doc.get("found"):
                entries_by_id[doc_id] = None
                continue

            if not (source := doc.get("_source")):
                entries_by_id[doc_id] = None
                continue

            try:
                entries_by_id[doc_id] = self._serializer.load_dict(data=source)
            except DeserializationError as e:
                logger.error(
                    "Failed to deserialize OpenSearch document in batch operation",
                    extra={
                        "collection": collection,
                        "document_id": doc_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                entries_by_id[doc_id] = None

        # Return entries in the same order as input keys
        return [entries_by_id.get(document_id) for document_id in document_ids]

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        index_name: str = self._get_index_name(collection=collection)
        document_id: str = self._get_document_id(key=key)

        document: dict[str, Any] = self._serializer.dump_dict(entry=managed_entry, key=key, collection=collection)

        try:
            _ = await _opensearch_index(
                self._client,
                index_name,
                document_id,
                document,
                refresh=True,
            )
        except OpenSearchSerializationError as e:
            msg = f"Failed to serialize document: {e}"
            raise SerializationError(message=msg) from e
        except Exception:
            raise

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        index_name: str = self._get_index_name(collection=collection)
        document_id: str = self._get_document_id(key=key)

        try:
            opensearch_response = await self._client.delete(index=index_name, id=document_id)
        except NotFoundError:
            # Document not found is not an error for delete operations
            return False

        body: dict[str, Any] = get_body_from_response(response=opensearch_response)

        if not (result := body.get("result")) or not isinstance(result, str):
            return False

        return result == "deleted"

    @override
    async def _get_collection_keys(self, *, collection: str, limit: int | None = None) -> list[str]:
        """Get up to 10,000 keys in the specified collection (eventually consistent)."""

        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)

        result = await self._client.search(
            index=self._get_index_name(collection=collection),
            body={
                "query": {
                    "term": {
                        "collection": collection,
                    },
                },
                "_source": False,
                "fields": ["key"],
                "size": limit,
            },
        )

        if not (hits := get_hits_from_response(response=result)):
            return []

        all_keys: list[str] = []

        for hit in hits:
            if not (key := get_first_value_from_field_in_hit(hit=hit, field="key", value_type=str)):
                continue

            all_keys.append(key)

        return all_keys

    @override
    async def _get_collection_names(self, *, limit: int | None = None) -> list[str]:
        """List up to 10,000 collections in the opensearch store (eventually consistent)."""

        limit = min(limit or DEFAULT_PAGE_SIZE, PAGE_LIMIT)

        search_response = await self._client.search(
            index=f"{self._index_prefix}-*",
            body={
                "aggs": {
                    "collections": {
                        "terms": {
                            "field": "collection",
                            "size": limit,
                        },
                    },
                },
                "size": 0,
            },
        )

        body: dict[str, Any] = get_body_from_response(response=search_response)
        aggregations: dict[str, Any] = get_aggregations_from_body(body=body)

        buckets = _get_aggregation_buckets(aggregations, "collections")

        return [_get_bucket_key(bucket) for bucket in buckets]

    @override
    async def _delete_collection(self, *, collection: str) -> bool:
        result = await self._client.delete_by_query(
            index=self._get_index_name(collection=collection),
            body={
                "query": {
                    "term": {
                        "collection": collection,
                    },
                },
            },
        )

        body: dict[str, Any] = get_body_from_response(response=result)

        if not (deleted := body.get("deleted")) or not isinstance(deleted, int):
            return False

        return deleted > 0

    @override
    async def _cull(self) -> None:
        ms_epoch = int(now_as_epoch() * 1000)
        _ = await self._client.delete_by_query(
            index=f"{self._index_prefix}-*",
            body={
                "query": {
                    "range": {
                        "expires_at": {"lt": ms_epoch},
                    },
                },
            },
        )
