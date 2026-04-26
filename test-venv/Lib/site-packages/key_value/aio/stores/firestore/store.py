from collections.abc import Sequence
from datetime import datetime
from typing import overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio.stores.base import (
    BaseContextManagerStore,
    BaseStore,
    BasicSerializationAdapter,
)

try:
    from google.auth.credentials import Credentials
    from google.cloud import firestore
except ImportError as e:
    msg = "FirestoreStore requires the `firestore` extra"
    raise ImportError(msg) from e


class FirestoreStore(BaseContextManagerStore, BaseStore):
    """Firestore-based key-value store.

    This store uses Firebase DB as the key-value storage.
    The data is stored in collections.
    """

    _client: firestore.AsyncClient

    @overload
    def __init__(self, client: firestore.AsyncClient, *, default_collection: str | None = None) -> None:
        """Initialize the Firestore store with a client.

        Args:
            client: The initialized Firestore client to use.
            default_collection: The default collection to use if no collection is provided.
        """

    @overload
    def __init__(
        self,
        *,
        credentials: Credentials | None = None,
        project: str | None = None,
        database: str | None = None,
        default_collection: str | None = None,
    ) -> None:
        """Initialize the Firestore store with credentials or Application Default Credentials.

        Args:
            credentials: Google credentials. If None, uses Application Default Credentials (ADC).
            project: Google project name. If None, inferred from credentials or environment.
            database: Database name, defaults to '(default)' if not provided.
            default_collection: The default collection to use if no collection is provided.
        """

    def __init__(
        self,
        client: firestore.AsyncClient | None = None,
        *,
        credentials: Credentials | None = None,
        project: str | None = None,
        database: str | None = None,
        default_collection: str | None = None,
    ) -> None:
        """Initialize the Firestore store.

        Can be initialized with:
        - An existing AsyncClient
        - Explicit credentials
        - No credentials (uses Application Default Credentials)

        Args:
            client: The initialized Firestore client to use. If provided, other connection args are ignored.
            credentials: Google credentials. If None, uses Application Default Credentials (ADC).
            project: Google project name. If None, inferred from credentials or environment.
            database: Database name, defaults to '(default)' if not provided.
            default_collection: The default collection to use if no collection is provided.
        """
        self._credentials = credentials
        self._project = project
        self._database = database
        serialization_adapter = BasicSerializationAdapter(value_format="string")

        if client:
            self._client = client
            client_provided_by_user = True
        else:
            self._client = firestore.AsyncClient(credentials=self._credentials, project=self._project, database=self._database)
            client_provided_by_user = False
        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided_by_user,
            serialization_adapter=serialization_adapter,
        )

    @override
    async def _setup(self) -> None:
        """Register client cleanup if we own the client."""
        if not self._client_provided_by_user:
            self._exit_stack.callback(self._client.close)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str | None = None) -> ManagedEntry | None:
        """Get a managed entry from Firestore."""
        collection = collection or self.default_collection
        response = await self._client.collection(collection).document(key).get()  # pyright: ignore[reportUnknownMemberType]
        doc = response.to_dict()
        if doc is None:
            return None
        return self._serialization_adapter.load_dict(data=doc)

    @override
    async def _get_managed_entries(self, *, collection: str, keys: Sequence[str]) -> list[ManagedEntry | None]:
        """Retrieve multiple managed entries from Firestore using batch get."""
        if not keys:
            return []

        # Get all documents in a single batch request
        doc_refs = [self._client.collection(collection).document(key) for key in keys]
        docs_by_id: dict[str, dict[str, object] | None] = {}

        async for doc in self._client.get_all(doc_refs):
            if doc.exists:
                docs_by_id[doc.id] = doc.to_dict()

        # Return results in the same order as keys
        result: list[ManagedEntry | None] = []
        for key in keys:
            doc = docs_by_id.get(key)
            if doc is None:
                result.append(None)
            else:
                result.append(self._serialization_adapter.load_dict(data=doc))
        return result

    @override
    async def _put_managed_entry(self, *, key: str, managed_entry: ManagedEntry, collection: str | None = None) -> None:
        """Store a managed entry in Firestore."""
        collection = collection or self.default_collection
        item = self._serialization_adapter.dump_dict(entry=managed_entry)
        await self._client.collection(collection).document(key).set(item)  # pyright: ignore[reportUnknownMemberType]

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
        """Store multiple managed entries in Firestore using batch write."""
        if not keys:
            return

        batch = self._client.batch()
        for key, managed_entry in zip(keys, managed_entries, strict=True):
            doc_ref = self._client.collection(collection).document(key)
            batch.set(doc_ref, self._serialization_adapter.dump_dict(entry=managed_entry))  # pyright: ignore[reportUnknownMemberType]
        await batch.commit()

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str | None = None) -> bool:
        """Delete a managed entry from Firestore.

        Returns True if the document existed and was deleted, False otherwise.
        """
        collection = collection or self.default_collection
        # Check if document exists before deleting
        doc_ref = self._client.collection(collection).document(key)
        doc_snapshot = await doc_ref.get()  # pyright: ignore[reportUnknownMemberType]
        exists: bool = doc_snapshot.exists

        # Always perform the delete operation (idempotent)
        await doc_ref.delete()

        return bool(exists)

    @override
    async def _delete_managed_entries(self, *, keys: Sequence[str], collection: str) -> int:
        """Delete multiple managed entries from Firestore using batch delete."""
        if not keys:
            return 0

        # First check which documents exist (batch get)
        doc_refs = [self._client.collection(collection).document(key) for key in keys]
        existing_count = 0
        async for doc in self._client.get_all(doc_refs):
            if doc.exists:
                existing_count += 1

        # Then batch delete all requested keys (idempotent)
        batch = self._client.batch()
        for key in keys:
            doc_ref = self._client.collection(collection).document(key)
            batch.delete(doc_ref)
        await batch.commit()

        return existing_count
