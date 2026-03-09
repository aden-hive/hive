"""
HuggingFace Hub Tool - Models, datasets, and spaces discovery via Hub API.

Supports:
- HuggingFace API token (HUGGINGFACE_TOKEN)
- Model, dataset, and space listing/search
- Repository details and user info

API Reference: https://huggingface.co/docs/hub/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

BASE_URL = "https://huggingface.co/api"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("huggingface")
    return os.getenv("HUGGINGFACE_TOKEN")


def _get(
    path: str, token: str | None, params: dict[str, Any] | None = None
) -> dict[str, Any] | list:
    """Make a GET request to the HuggingFace Hub API."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(
            f"{BASE_URL}{path}",
            headers=headers,
            params=params or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your HUGGINGFACE_TOKEN."}
        if resp.status_code == 404:
            return {"error": f"Not found: {path}"}
        if resp.status_code != 200:
            return {"error": f"HuggingFace API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to HuggingFace timed out"}
    except Exception as e:
        return {"error": f"HuggingFace request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "HUGGINGFACE_TOKEN not set",
        "help": "Get a token at https://huggingface.co/settings/tokens",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register HuggingFace Hub tools with the MCP server."""

    @mcp.tool()
    def huggingface_search_models(
        query: str = "",
        author: str = "",
        sort: str = "downloads",
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search for models on HuggingFace Hub.

        Args:
            query: Search query text (optional)
            author: Filter by author/organization (optional)
            sort: Sort by: downloads, likes, lastModified (default downloads)
            limit: Max results (1-100, default 20)

        Returns:
            Dict with models list (id, author, downloads, likes, pipeline_tag, tags)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "sort": sort,
            "direction": "-1",
            "limit": max(1, min(limit, 100)),
        }
        if query:
            params["search"] = query
        if author:
            params["author"] = author

        data = _get("/models", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        models = []
        for m in data if isinstance(data, list) else []:
            models.append(
                {
                    "id": m.get("id", ""),
                    "author": m.get("author", ""),
                    "downloads": m.get("downloads", 0),
                    "likes": m.get("likes", 0),
                    "pipeline_tag": m.get("pipeline_tag", ""),
                    "tags": m.get("tags", [])[:10],
                    "last_modified": m.get("lastModified", ""),
                }
            )
        return {"models": models, "count": len(models)}

    @mcp.tool()
    def huggingface_get_model(model_id: str) -> dict[str, Any]:
        """
        Get details about a specific model on HuggingFace Hub.

        Args:
            model_id: Model ID (e.g. "meta-llama/Llama-3-8B")

        Returns:
            Dict with model details (id, author, downloads, pipeline_tag, config, etc.)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not model_id:
            return {"error": "model_id is required"}

        data = _get(f"/models/{model_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data

        m = data if isinstance(data, dict) else {}
        return {
            "id": m.get("id", ""),
            "author": m.get("author", ""),
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "pipeline_tag": m.get("pipeline_tag", ""),
            "tags": m.get("tags", []),
            "library_name": m.get("library_name", ""),
            "model_index": m.get("model-index"),
            "card_data": m.get("cardData"),
            "private": m.get("private", False),
            "last_modified": m.get("lastModified", ""),
            "created_at": m.get("createdAt", ""),
        }

    @mcp.tool()
    def huggingface_search_datasets(
        query: str = "",
        author: str = "",
        sort: str = "downloads",
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search for datasets on HuggingFace Hub.

        Args:
            query: Search query text (optional)
            author: Filter by author/organization (optional)
            sort: Sort by: downloads, likes, lastModified (default downloads)
            limit: Max results (1-100, default 20)

        Returns:
            Dict with datasets list (id, author, downloads, likes, tags)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "sort": sort,
            "direction": "-1",
            "limit": max(1, min(limit, 100)),
        }
        if query:
            params["search"] = query
        if author:
            params["author"] = author

        data = _get("/datasets", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        datasets = []
        for d in data if isinstance(data, list) else []:
            datasets.append(
                {
                    "id": d.get("id", ""),
                    "author": d.get("author", ""),
                    "downloads": d.get("downloads", 0),
                    "likes": d.get("likes", 0),
                    "tags": d.get("tags", [])[:10],
                    "last_modified": d.get("lastModified", ""),
                }
            )
        return {"datasets": datasets, "count": len(datasets)}

    @mcp.tool()
    def huggingface_get_dataset(dataset_id: str) -> dict[str, Any]:
        """
        Get details about a specific dataset on HuggingFace Hub.

        Args:
            dataset_id: Dataset ID (e.g. "squad", "openai/gsm8k")

        Returns:
            Dict with dataset details
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not dataset_id:
            return {"error": "dataset_id is required"}

        data = _get(f"/datasets/{dataset_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data

        d = data if isinstance(data, dict) else {}
        return {
            "id": d.get("id", ""),
            "author": d.get("author", ""),
            "downloads": d.get("downloads", 0),
            "likes": d.get("likes", 0),
            "tags": d.get("tags", []),
            "card_data": d.get("cardData"),
            "private": d.get("private", False),
            "last_modified": d.get("lastModified", ""),
            "created_at": d.get("createdAt", ""),
        }

    @mcp.tool()
    def huggingface_search_spaces(
        query: str = "",
        author: str = "",
        sort: str = "likes",
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search for Spaces on HuggingFace Hub.

        Args:
            query: Search query text (optional)
            author: Filter by author/organization (optional)
            sort: Sort by: likes, lastModified (default likes)
            limit: Max results (1-100, default 20)

        Returns:
            Dict with spaces list (id, author, likes, sdk, tags)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "sort": sort,
            "direction": "-1",
            "limit": max(1, min(limit, 100)),
        }
        if query:
            params["search"] = query
        if author:
            params["author"] = author

        data = _get("/spaces", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        spaces = []
        for s in data if isinstance(data, list) else []:
            spaces.append(
                {
                    "id": s.get("id", ""),
                    "author": s.get("author", ""),
                    "likes": s.get("likes", 0),
                    "sdk": s.get("sdk", ""),
                    "tags": s.get("tags", [])[:10],
                    "last_modified": s.get("lastModified", ""),
                }
            )
        return {"spaces": spaces, "count": len(spaces)}

    @mcp.tool()
    def huggingface_whoami() -> dict[str, Any]:
        """
        Get info about the authenticated HuggingFace user.

        Returns:
            Dict with user info (name, fullname, email, orgs)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("/whoami-v2", token)
        if isinstance(data, dict) and "error" in data:
            return data

        u = data if isinstance(data, dict) else {}
        orgs = [
            {"name": o.get("name", ""), "role": o.get("roleInOrg", "")} for o in u.get("orgs", [])
        ]
        return {
            "name": u.get("name", ""),
            "fullname": u.get("fullname", ""),
            "email": u.get("email", ""),
            "avatar_url": u.get("avatarUrl", ""),
            "orgs": orgs,
            "type": u.get("type", ""),
        }
