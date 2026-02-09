"""ChromaDB vector store adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import chromadb
from chromadb.config import Settings as ChromaSettings

if TYPE_CHECKING:
    from chromadb import Collection


class ChromaDBStore:
    """ChromaDB adapter for vector storage and similarity search."""

    def __init__(
        self,
        persist_directory: str = "./chroma_db",
        collection_name: str = "default_collection",
    ):
        """
        Initialize ChromaDB client.
        Args:
            persist_directory: Path to persist the database
            collection_name: Name of the collection to use
        """
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection_name = collection_name
        self._collection: Collection | None = None

    def get_collection(self) -> Collection:
        """Get or create the collection."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Add or update documents in the collection.
        Args:
            ids: List of document IDs
            documents: List of document texts
            metadatas: Optional list of metadata dictionaries
        Returns:
            Dict with success status
        """
        try:
            collection = self.get_collection()
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas or [{}] * len(ids),
            )
            return {"success": True, "count": len(ids)}
        except Exception as e:
            return {"error": f"Failed to upsert documents: {e}"}

    def search(
        self,
        query_texts: list[str],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Search for similar documents.
        Args:
            query_texts: List of query texts
            n_results: Number of results to return per query
            where: Optional metadata filter
        Returns:
            Dict with search results
        """
        try:
            collection = self.get_collection()
            results = collection.query(
                query_texts=query_texts,
                n_results=n_results,
                where=where,
            )
            return {"success": True, "data": results}
        except Exception as e:
            return {"error": f"Failed to search documents: {e}"}

    def delete(self, ids: list[str]) -> dict[str, Any]:
        """
        Delete documents by ID.
        Args:
            ids: List of document IDs to delete
        Returns:
            Dict with success status
        """
        try:
            collection = self.get_collection()
            collection.delete(ids=ids)
            return {"success": True, "deleted_count": len(ids)}
        except Exception as e:
            return {"error": f"Failed to delete documents: {e}"}

    def count(self) -> dict[str, Any]:
        """
        Get the count of documents in the collection.
        Returns:
            Dict with count
        """
        try:
            collection = self.get_collection()
            count = collection.count()
            return {"success": True, "count": count}
        except Exception as e:
            return {"error": f"Failed to get count: {e}"}
