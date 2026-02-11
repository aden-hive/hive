"""
Vector Database Tool - Manage vector stores for semantic search.

Supports:
- ChromaDB (local persistent storage)
- Future: Pinecone, Qdrant, PGVector

API Reference: https://docs.trychroma.com/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register vector database tools with the MCP server."""

    def _get_chroma_config() -> dict[str, str]:
        """Get ChromaDB configuration from environment."""
        return {
            "persist_directory": os.getenv("CHROMA_PERSIST_DIR"),
            "collection_name": os.getenv("CHROMA_COLLECTION_NAME", "default_collection"),
        }

    def _ensure_config(config: dict) -> dict | None:
        """Check if config is valid, return error dict if not."""
        if not config["persist_directory"]:
            return {
                "error": "ChromaDB persistence directory not configured",
                "help": "Set CHROMA_PERSIST_DIR environment variable",
            }
        return None

    @mcp.tool()
    def vector_db_upsert(
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        collection_name: str | None = None,
        persist_directory: str | None = None,
    ) -> dict:
        """
        Add or update documents in the vector database.

        Args:
            ids: List of unique document IDs
            documents: List of document texts to store
            metadatas: Optional list of metadata dictionaries (one per document)
            collection_name: Optional collection name (defaults to env var or "default_collection")
            persist_directory: Optional persist directory (defaults to env var or "./chroma_db")

        Returns:
            Dict with success status and count of documents added/updated
        """
        from aden_tools.tools.vector_db_tool.stores.chromadb import ChromaDBStore

        if not ids or not documents:
            return {"error": "Both ids and documents are required"}
        if len(ids) != len(documents):
            return {"error": "ids and documents must have the same length"}
        if metadatas and len(metadatas) != len(ids):
            return {"error": "metadatas must have the same length as ids"}

        try:
            config = _get_chroma_config()
            # If explicit paths not provided, check env vars
            if not persist_directory and (error := _ensure_config(config)):
                return error

            store = ChromaDBStore(
                persist_directory=persist_directory or config["persist_directory"],
                collection_name=collection_name or config["collection_name"],
            )
            return store.upsert(ids, documents, metadatas)
        except Exception as e:
            return {"error": f"Vector DB upsert failed: {e}"}

    @mcp.tool()
    def vector_db_search(
        query_texts: list[str],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        collection_name: str | None = None,
        persist_directory: str | None = None,
    ) -> dict:
        """
        Search for similar documents in the vector database.

        Args:
            query_texts: List of query texts to search for
            n_results: Number of results to return per query (default 5)
            where: Optional metadata filter (e.g., {"state": "open"})
            collection_name: Optional collection name (defaults to env var or "default_collection")
            persist_directory: Optional persist directory (defaults to env var or "./chroma_db")

        Returns:
            Dict with search results including ids, documents, metadatas, and distances
        """
        from aden_tools.tools.vector_db_tool.stores.chromadb import ChromaDBStore

        if not query_texts:
            return {"error": "query_texts is required"}

        try:
            config = _get_chroma_config()
            if not persist_directory and (error := _ensure_config(config)):
                return error

            store = ChromaDBStore(
                persist_directory=persist_directory or config["persist_directory"],
                collection_name=collection_name or config["collection_name"],
            )
            return store.search(query_texts, n_results, where)
        except Exception as e:
            return {"error": f"Vector DB search failed: {e}"}

    @mcp.tool()
    def vector_db_delete(
        ids: list[str],
        collection_name: str | None = None,
        persist_directory: str | None = None,
    ) -> dict:
        """
        Delete documents from the vector database.

        Args:
            ids: List of document IDs to delete
            collection_name: Optional collection name (defaults to env var or "default_collection")
            persist_directory: Optional persist directory (defaults to env var or "./chroma_db")

        Returns:
            Dict with success status and count of deleted documents
        """
        from aden_tools.tools.vector_db_tool.stores.chromadb import ChromaDBStore

        if not ids:
            return {"error": "ids is required"}

        try:
            config = _get_chroma_config()
            if not persist_directory and (error := _ensure_config(config)):
                return error

            store = ChromaDBStore(
                persist_directory=persist_directory or config["persist_directory"],
                collection_name=collection_name or config["collection_name"],
            )
            return store.delete(ids)
        except Exception as e:
            return {"error": f"Vector DB delete failed: {e}"}

    @mcp.tool()
    def vector_db_count(
        collection_name: str | None = None,
        persist_directory: str | None = None,
    ) -> dict:
        """
        Get the count of documents in a collection.

        Args:
            collection_name: Optional collection name (defaults to env var or "default_collection")
            persist_directory: Optional persist directory (defaults to env var or "./chroma_db")

        Returns:
            Dict with count of documents in the collection
        """
        from aden_tools.tools.vector_db_tool.stores.chromadb import ChromaDBStore

        try:
            config = _get_chroma_config()
            if not persist_directory and (error := _ensure_config(config)):
                return error

            store = ChromaDBStore(
                persist_directory=persist_directory or config["persist_directory"],
                collection_name=collection_name or config["collection_name"],
            )
            return store.count()
        except Exception as e:
            return {"error": f"Vector DB count failed: {e}"}
