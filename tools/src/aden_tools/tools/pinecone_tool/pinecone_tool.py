"""
Pinecone Tool - Vector database for semantic search and RAG workflows.

Supports:
- Pinecone API key (PINECONE_API_KEY)
- Index management (list, create, describe, delete)
- Vector operations (upsert, query, fetch, delete)
- Index stats and namespace listing

API Reference: https://docs.pinecone.io/reference/api/introduction
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

CONTROL_PLANE = "https://api.pinecone.io"
API_VERSION = "2025-04"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("pinecone")
    return os.getenv("PINECONE_API_KEY")


def _headers(token: str) -> dict[str, str]:
    return {
        "Api-Key": token,
        "Content-Type": "application/json",
        "X-Pinecone-Api-Version": API_VERSION,
    }


def _control(method: str, path: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a control-plane request to api.pinecone.io."""
    try:
        resp = getattr(httpx, method)(
            f"{CONTROL_PLANE}{path}",
            headers=_headers(token),
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your PINECONE_API_KEY."}
        if resp.status_code == 202:
            return {"status": "accepted"}
        if resp.status_code not in (200, 201):
            return {"error": f"Pinecone API error {resp.status_code}: {resp.text[:500]}"}
        if not resp.content:
            return {"status": "ok"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Pinecone timed out"}
    except Exception as e:
        return {"error": f"Pinecone request failed: {e!s}"}


def _data(method: str, host: str, path: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a data-plane request to {index_host}."""
    url = host if host.startswith("https://") else f"https://{host}"
    try:
        resp = getattr(httpx, method)(
            f"{url}{path}",
            headers=_headers(token),
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your PINECONE_API_KEY."}
        if resp.status_code not in (200, 201):
            return {"error": f"Pinecone API error {resp.status_code}: {resp.text[:500]}"}
        if not resp.content:
            return {}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Pinecone timed out"}
    except Exception as e:
        return {"error": f"Pinecone request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "PINECONE_API_KEY not set",
        "help": "Get an API key at https://app.pinecone.io/ under API Keys",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Pinecone tools with the MCP server."""

    # ── Index Management (Control Plane) ──

    @mcp.tool()
    def pinecone_list_indexes() -> dict[str, Any]:
        """
        List all indexes in your Pinecone project.

        Returns:
            Dict with indexes list (name, dimension, metric, host, status, vector_type)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _control("get", "/indexes", token)
        if "error" in data:
            return data

        indexes = []
        for idx in data.get("indexes", []):
            indexes.append(
                {
                    "name": idx.get("name", ""),
                    "dimension": idx.get("dimension", 0),
                    "metric": idx.get("metric", ""),
                    "host": idx.get("host", ""),
                    "vector_type": idx.get("vector_type", "dense"),
                    "state": (idx.get("status") or {}).get("state", ""),
                    "ready": (idx.get("status") or {}).get("ready", False),
                }
            )
        return {"indexes": indexes, "count": len(indexes)}

    @mcp.tool()
    def pinecone_create_index(
        name: str,
        dimension: int,
        metric: str = "cosine",
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> dict[str, Any]:
        """
        Create a new serverless Pinecone index.

        Args:
            name: Index name (1-45 chars, lowercase alphanumeric and hyphens)
            dimension: Vector dimension (1-20000)
            metric: Distance metric: cosine, euclidean, or dotproduct (default cosine)
            cloud: Cloud provider: aws, gcp, or azure (default aws)
            region: Cloud region (default us-east-1)

        Returns:
            Dict with created index details
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not name or not dimension:
            return {"error": "name and dimension are required"}

        body = {
            "name": name,
            "dimension": dimension,
            "metric": metric,
            "spec": {"serverless": {"cloud": cloud, "region": region}},
        }
        data = _control("post", "/indexes", token, json=body)
        if "error" in data:
            return data

        return {
            "name": data.get("name", name),
            "dimension": data.get("dimension", dimension),
            "metric": data.get("metric", metric),
            "host": data.get("host", ""),
            "status": "created",
        }

    @mcp.tool()
    def pinecone_describe_index(index_name: str) -> dict[str, Any]:
        """
        Get details about a specific Pinecone index.

        Args:
            index_name: Name of the index

        Returns:
            Dict with index configuration and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_name:
            return {"error": "index_name is required"}

        data = _control("get", f"/indexes/{index_name}", token)
        if "error" in data:
            return data

        return {
            "name": data.get("name", ""),
            "dimension": data.get("dimension", 0),
            "metric": data.get("metric", ""),
            "host": data.get("host", ""),
            "vector_type": data.get("vector_type", "dense"),
            "state": (data.get("status") or {}).get("state", ""),
            "ready": (data.get("status") or {}).get("ready", False),
            "deletion_protection": data.get("deletion_protection", "disabled"),
            "spec": data.get("spec", {}),
        }

    @mcp.tool()
    def pinecone_delete_index(index_name: str) -> dict[str, Any]:
        """
        Delete a Pinecone index. This is irreversible.

        Args:
            index_name: Name of the index to delete

        Returns:
            Dict with deletion status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_name:
            return {"error": "index_name is required"}

        data = _control("delete", f"/indexes/{index_name}", token)
        if "error" in data:
            return data

        return {"index_name": index_name, "status": "deleted"}

    # ── Vector Operations (Data Plane) ──

    @mcp.tool()
    def pinecone_upsert_vectors(
        index_host: str,
        vectors: list[dict[str, Any]],
        namespace: str = "",
    ) -> dict[str, Any]:
        """
        Upsert vectors into a Pinecone index.

        Args:
            index_host: Index host URL (from describe_index or list_indexes)
            vectors: List of vector dicts, each with 'id' (str) and 'values' (list[float]),
                     optionally 'metadata' (dict). Max 1000 per call.
            namespace: Target namespace (optional, default is "")

        Returns:
            Dict with upserted count
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_host or not vectors:
            return {"error": "index_host and vectors are required"}

        body: dict[str, Any] = {"vectors": vectors}
        if namespace:
            body["namespace"] = namespace

        data = _data("post", index_host, "/vectors/upsert", token, json=body)
        if "error" in data:
            return data

        return {"upserted_count": data.get("upsertedCount", 0)}

    @mcp.tool()
    def pinecone_query_vectors(
        index_host: str,
        vector: list[float] | None = None,
        id: str = "",
        top_k: int = 10,
        namespace: str = "",
        filter: dict[str, Any] | None = None,
        include_metadata: bool = True,
        include_values: bool = False,
    ) -> dict[str, Any]:
        """
        Query a Pinecone index for similar vectors.

        Args:
            index_host: Index host URL (from describe_index or list_indexes)
            vector: Query vector (list of floats). Required if id is not provided.
            id: Query by existing vector ID instead of providing a vector.
            top_k: Number of results to return (1-10000, default 10)
            namespace: Namespace to query (optional)
            filter: Metadata filter dict (optional)
            include_metadata: Include metadata in results (default True)
            include_values: Include vector values in results (default False)

        Returns:
            Dict with matches (id, score, metadata) and namespace
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_host:
            return {"error": "index_host is required"}
        if not vector and not id:
            return {"error": "Either vector or id is required"}

        body: dict[str, Any] = {
            "topK": max(1, min(top_k, 10000)),
            "includeMetadata": include_metadata,
            "includeValues": include_values,
        }
        if vector:
            body["vector"] = vector
        if id:
            body["id"] = id
        if namespace:
            body["namespace"] = namespace
        if filter:
            body["filter"] = filter

        data = _data("post", index_host, "/query", token, json=body)
        if "error" in data:
            return data

        matches = []
        for m in data.get("matches", []):
            match: dict[str, Any] = {
                "id": m.get("id", ""),
                "score": m.get("score", 0.0),
            }
            if include_metadata and m.get("metadata"):
                match["metadata"] = m["metadata"]
            if include_values and m.get("values"):
                match["values"] = m["values"]
            matches.append(match)

        return {
            "matches": matches,
            "namespace": data.get("namespace", ""),
        }

    @mcp.tool()
    def pinecone_fetch_vectors(
        index_host: str,
        ids: list[str],
        namespace: str = "",
    ) -> dict[str, Any]:
        """
        Fetch vectors by ID from a Pinecone index.

        Args:
            index_host: Index host URL (from describe_index or list_indexes)
            ids: List of vector IDs to fetch
            namespace: Namespace to fetch from (optional)

        Returns:
            Dict with vectors keyed by ID
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_host or not ids:
            return {"error": "index_host and ids are required"}

        params: dict[str, Any] = {"ids": ids}
        if namespace:
            params["namespace"] = namespace

        data = _data("get", index_host, "/vectors/fetch", token, params=params)
        if "error" in data:
            return data

        vectors = {}
        for vid, vdata in data.get("vectors", {}).items():
            vectors[vid] = {
                "id": vdata.get("id", vid),
                "values": vdata.get("values", []),
                "metadata": vdata.get("metadata"),
            }

        return {"vectors": vectors, "namespace": data.get("namespace", "")}

    @mcp.tool()
    def pinecone_delete_vectors(
        index_host: str,
        ids: list[str] | None = None,
        namespace: str = "",
        delete_all: bool = False,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Delete vectors from a Pinecone index.

        Args:
            index_host: Index host URL (from describe_index or list_indexes)
            ids: List of vector IDs to delete (1-1000). Mutually exclusive with delete_all/filter.
            namespace: Namespace to delete from (optional)
            delete_all: Delete all vectors in the namespace (default False)
            filter: Metadata filter for selective deletion (optional)

        Returns:
            Dict with deletion status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_host:
            return {"error": "index_host is required"}
        if not ids and not delete_all and not filter:
            return {"error": "Provide ids, delete_all=True, or a filter"}

        body: dict[str, Any] = {}
        if ids:
            body["ids"] = ids
        if namespace:
            body["namespace"] = namespace
        if delete_all:
            body["deleteAll"] = True
        if filter:
            body["filter"] = filter

        data = _data("post", index_host, "/vectors/delete", token, json=body)
        if "error" in data:
            return data

        return {"status": "deleted"}

    @mcp.tool()
    def pinecone_index_stats(index_host: str) -> dict[str, Any]:
        """
        Get statistics for a Pinecone index, including namespace vector counts.

        Args:
            index_host: Index host URL (from describe_index or list_indexes)

        Returns:
            Dict with namespaces, dimension, total vector count, metric
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not index_host:
            return {"error": "index_host is required"}

        data = _data("post", index_host, "/describe_index_stats", token, json={})
        if "error" in data:
            return data

        namespaces = {}
        for ns_name, ns_data in data.get("namespaces", {}).items():
            namespaces[ns_name] = {"vector_count": ns_data.get("vectorCount", 0)}

        return {
            "namespaces": namespaces,
            "dimension": data.get("dimension", 0),
            "total_vector_count": data.get("totalVectorCount", 0),
            "metric": data.get("metric", ""),
            "vector_type": data.get("vectorType", ""),
        }
