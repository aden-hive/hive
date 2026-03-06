"""MongoDB Atlas Data API integration.

Provides document CRUD and aggregation via the MongoDB Atlas Data API.
Requires MONGODB_DATA_API_URL, MONGODB_API_KEY, and MONGODB_DATA_SOURCE.

Note: The Atlas Data API reached EOL in September 2025. Compatible
replacements like Delbridge and RESTHeart use the same interface.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _get_config() -> tuple[str, str, str] | dict:
    """Return (base_url, api_key, data_source) or error dict."""
    url = os.getenv("MONGODB_DATA_API_URL", "").rstrip("/")
    api_key = os.getenv("MONGODB_API_KEY", "")
    data_source = os.getenv("MONGODB_DATA_SOURCE", "")
    if not url or not api_key:
        return {
            "error": "MONGODB_DATA_API_URL and MONGODB_API_KEY are required",
            "help": "Set MONGODB_DATA_API_URL and MONGODB_API_KEY environment variables",
        }
    return url, api_key, data_source


def _request(url: str, api_key: str, action: str, body: dict) -> dict:
    """Send a POST request to the Data API."""
    endpoint = f"{url}/action/{action}"
    resp = httpx.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        json=body,
        timeout=30,
    )
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register MongoDB tools."""

    @mcp.tool()
    def mongodb_find(
        database: str,
        collection: str,
        filter: str = "{}",
        projection: str = "",
        sort: str = "",
        limit: int = 20,
    ) -> dict:
        """Find documents in a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            filter: JSON query filter (e.g. '{"status": "active"}').
            projection: JSON projection (e.g. '{"name": 1, "_id": 0}').
            sort: JSON sort specification (e.g. '{"created": -1}').
            limit: Maximum documents to return (default 20).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}

        body: dict[str, Any] = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
            "limit": limit,
        }
        try:
            body["filter"] = json.loads(filter)
        except json.JSONDecodeError:
            return {"error": "filter must be valid JSON"}
        if projection:
            try:
                body["projection"] = json.loads(projection)
            except json.JSONDecodeError:
                return {"error": "projection must be valid JSON"}
        if sort:
            try:
                body["sort"] = json.loads(sort)
            except json.JSONDecodeError:
                return {"error": "sort must be valid JSON"}

        data = _request(url, api_key, "find", body)
        if "error" in data:
            return data
        docs = data.get("documents", [])
        return {"count": len(docs), "documents": docs}

    @mcp.tool()
    def mongodb_find_one(
        database: str,
        collection: str,
        filter: str = "{}",
        projection: str = "",
    ) -> dict:
        """Find a single document in a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            filter: JSON query filter (e.g. '{"_id": {"$oid": "..."}}').
            projection: JSON projection (e.g. '{"name": 1}').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}

        body: dict[str, Any] = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
        }
        try:
            body["filter"] = json.loads(filter)
        except json.JSONDecodeError:
            return {"error": "filter must be valid JSON"}
        if projection:
            try:
                body["projection"] = json.loads(projection)
            except json.JSONDecodeError:
                return {"error": "projection must be valid JSON"}

        data = _request(url, api_key, "findOne", body)
        if "error" in data:
            return data
        doc = data.get("document")
        if doc is None:
            return {"error": "no document found matching filter"}
        return doc

    @mcp.tool()
    def mongodb_insert_one(
        database: str,
        collection: str,
        document: str,
    ) -> dict:
        """Insert a single document into a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            document: JSON document to insert (e.g. '{"name": "Alice", "age": 30}').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}
        if not document:
            return {"error": "document is required"}

        try:
            doc = json.loads(document)
        except json.JSONDecodeError:
            return {"error": "document must be valid JSON"}

        body = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
            "document": doc,
        }
        data = _request(url, api_key, "insertOne", body)
        if "error" in data:
            return data
        return {"result": "inserted", "insertedId": data.get("insertedId")}

    @mcp.tool()
    def mongodb_update_one(
        database: str,
        collection: str,
        filter: str,
        update: str,
        upsert: bool = False,
    ) -> dict:
        """Update a single document in a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            filter: JSON query filter to match the document.
            update: JSON update operations (e.g. '{"$set": {"status": "active"}}').
            upsert: If true, insert a new document when no match is found.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}
        if not filter or not update:
            return {"error": "filter and update are required"}

        try:
            filter_obj = json.loads(filter)
        except json.JSONDecodeError:
            return {"error": "filter must be valid JSON"}
        try:
            update_obj = json.loads(update)
        except json.JSONDecodeError:
            return {"error": "update must be valid JSON"}

        body = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
            "filter": filter_obj,
            "update": update_obj,
            "upsert": upsert,
        }
        data = _request(url, api_key, "updateOne", body)
        if "error" in data:
            return data
        result = {
            "matchedCount": data.get("matchedCount", 0),
            "modifiedCount": data.get("modifiedCount", 0),
        }
        if "upsertedId" in data:
            result["upsertedId"] = data["upsertedId"]
        return result

    @mcp.tool()
    def mongodb_delete_one(
        database: str,
        collection: str,
        filter: str,
    ) -> dict:
        """Delete a single document from a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            filter: JSON query filter to match the document to delete.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}
        if not filter:
            return {"error": "filter is required"}

        try:
            filter_obj = json.loads(filter)
        except json.JSONDecodeError:
            return {"error": "filter must be valid JSON"}

        body = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
            "filter": filter_obj,
        }
        data = _request(url, api_key, "deleteOne", body)
        if "error" in data:
            return data
        return {"deletedCount": data.get("deletedCount", 0)}

    @mcp.tool()
    def mongodb_aggregate(
        database: str,
        collection: str,
        pipeline: str,
    ) -> dict:
        """Run an aggregation pipeline on a MongoDB collection.

        Args:
            database: Database name.
            collection: Collection name.
            pipeline: JSON array of pipeline stages
                (e.g. '[{"$match": {"status": "active"}}]').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        url, api_key, data_source = cfg
        if not database or not collection:
            return {"error": "database and collection are required"}
        if not pipeline:
            return {"error": "pipeline is required"}

        try:
            pipeline_obj = json.loads(pipeline)
        except json.JSONDecodeError:
            return {"error": "pipeline must be valid JSON"}
        if not isinstance(pipeline_obj, list):
            return {"error": "pipeline must be a JSON array"}

        body = {
            "dataSource": data_source,
            "database": database,
            "collection": collection,
            "pipeline": pipeline_obj,
        }
        data = _request(url, api_key, "aggregate", body)
        if "error" in data:
            return data
        docs = data.get("documents", [])
        return {"count": len(docs), "documents": docs}
