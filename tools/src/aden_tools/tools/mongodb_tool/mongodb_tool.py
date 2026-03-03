"""
MongoDB Tool - Perform database operations (CRUD) via MongoDB Atlas.

Supports:
- MongoDB Connection String URIs (MONGODB_URI)

API Reference: https://www.mongodb.com/docs/drivers/python/
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from aden_tools.credentials import CredentialStoreAdapter

# Global cache to reuse the connection pool across tool calls.
# Unlike HTTP requests, opening a new DB connection per call is very expensive.
_global_mongo_client: MongoClient | None = None


class _MongoClient:
    """Internal client wrapping MongoDB operations."""

    def __init__(self, uri: str):
        global _global_mongo_client
        if _global_mongo_client is None:
            _global_mongo_client = MongoClient(uri)
        self._client = _global_mongo_client

    def _serialize_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Convert MongoDB ObjectIds to strings for JSON serialization."""
        if doc and "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def ping(self) -> dict[str, Any]:
        """Verify database connectivity."""
        try:
            self._client.admin.command('ping')
            return {
                "success": True, 
                "message": "Successfully connected to MongoDB Atlas! The database is responsive."
            }
        except PyMongoError as e:
            return {"error": f"Database connection error: {e}"}

    def insert_document(
        self, 
        database: str, 
        collection: str, 
        document: dict[str, Any]
    ) -> dict[str, Any]:
        """Insert a document into a collection."""
        try:
            db = self._client[database]
            col = db[collection]
            result = col.insert_one(document)
            return {
                "success": True,
                "inserted_id": str(result.inserted_id)
            }
        except PyMongoError as e:
            return {"error": f"Database insertion error: {e}"}

    def find_documents(
        self, 
        database: str, 
        collection: str, 
        query: dict[str, Any], 
        limit: int
    ) -> dict[str, Any]:
        """Find documents matching a query filter."""
        try:
            db = self._client[database]
            col = db[collection]
            cursor = col.find(query).limit(limit)
            
            documents = [self._serialize_doc(doc) for doc in cursor]
            
            return {
                "success": True,
                "count": len(documents),
                "data": documents
            }
        except PyMongoError as e:
            return {"error": f"Database query error: {e}"}

    def list_collections(self, database: str) -> dict[str, Any]:
        """List all collections in a database."""
        try:
            db = self._client[database]
            collections = db.list_collection_names()
            return {
                "success": True,
                "collections": collections
            }
        except PyMongoError as e:
            return {"error": f"Database list collections error: {e}"}

    def aggregate_documents(
        self, 
        database: str, 
        collection: str, 
        pipeline: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Run an aggregation pipeline."""
        try:
            db = self._client[database]
            col = db[collection]
            cursor = col.aggregate(pipeline)
            
            documents = [self._serialize_doc(doc) for doc in cursor]
            
            return {
                "success": True,
                "count": len(documents),
                "data": documents
            }
        except PyMongoError as e:
            return {"error": f"Database aggregation error: {e}"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register MongoDB tools with the MCP server."""

    def _get_uri() -> str | None:
        """Get MongoDB URI from credential manager or environment."""
        if credentials is not None:
            uri = credentials.get("mongodb")
            if uri is not None and not isinstance(uri, str):
                raise TypeError(
                    f"Expected string from credentials.get('mongodb'), got {type(uri).__name__}"
                )
            return uri
        return os.getenv("MONGODB_URI")

    def _get_client() -> _MongoClient | dict[str, str]:
        """Get a MongoDB client, or return an error dict if no credentials."""
        uri = _get_uri()
        if not uri:
            return {
                "error": "MongoDB URI not configured",
                "help": (
                    "Set MONGODB_URI environment variable or configure via "
                    "credential store. Get your URI from MongoDB Atlas dashboard."
                ),
            }
        return _MongoClient(uri)

    @mcp.tool()
    def mongodb_ping_database() -> dict[str, Any]:
        """
        Ping the MongoDB database to verify the connection.

        Use this to check if the database is accessible, properly configured,
        and responsive before attempting data operations.

        Returns:
            Dict with success message, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        return client.ping()

    @mcp.tool()
    def mongodb_insert_document(
        database: str,
        collection: str,
        document_json: str,
    ) -> dict[str, Any]:
        """
        Insert a new document into a specific MongoDB collection.

        Use this to save new records, users, logs, or any JSON data.

        Args:
            database: Target database name.
            collection: Target collection name.
            document_json: Valid JSON string representing the document to insert.

        Returns:
            Dict with the new document's inserted_id, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            document = json.loads(document_json)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON format provided in document_json."}

        return client.insert_document(
            database=database, 
            collection=collection, 
            document=document
        )

    @mcp.tool()
    def mongodb_find_document(
        database: str,
        collection: str,
        query_json: str = "{}",
        limit: int = 5,
    ) -> dict[str, Any]:
        """
        Find documents in a MongoDB database based on a JSON query filter.

        Use this to retrieve records. Pass an empty JSON string "{}" to get all records up to the limit.

        Args:
            database: Target database name.
            collection: Target collection name.
            query_json: JSON string representing the MongoDB query filter (e.g., '{"status": "active"}').
            limit: Maximum number of documents to return (default is 5 to prevent massive outputs).

        Returns:
            Dict containing the match count and the data array, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            query = json.loads(query_json)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON format provided in query_json."}

        return client.find_documents(
            database=database, 
            collection=collection, 
            query=query, 
            limit=limit
        )

    @mcp.tool()
    def mongodb_list_collections(database: str) -> dict[str, Any]:
        """
        List all collections available in a specific MongoDB database.

        Use this to explore the database structure and see what data is available.

        Args:
            database: Target database name.

        Returns:
            Dict containing the list of collection names, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        return client.list_collections(database=database)

    @mcp.tool()
    def mongodb_aggregate(
        database: str,
        collection: str,
        pipeline_json: str,
    ) -> dict[str, Any]:
        """
        Run a complex aggregation pipeline on a MongoDB collection.

        Use this for analytics, filtering, grouping, and transforming data.

        Args:
            database: Target database name.
            collection: Target collection name.
            pipeline_json: JSON string representing the aggregation pipeline (array of stages).

        Returns:
            Dict containing the result count and data array, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            pipeline = json.loads(pipeline_json)
            if not isinstance(pipeline, list):
                return {"error": "Pipeline must be a JSON array of aggregation stages."}
        except json.JSONDecodeError:
            return {"error": "Invalid JSON format provided in pipeline_json."}

        return client.aggregate_documents(
            database=database, 
            collection=collection, 
            pipeline=pipeline
        )
