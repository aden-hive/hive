"""
HuggingFace Hub Tool - Models, datasets, spaces discovery and inference via Hub API.

Supports:
- HuggingFace API token (HUGGINGFACE_TOKEN)
- Model, dataset, and space listing/search
- Repository details and user info
- Model inference (text-generation, summarization, classification, etc.)
- Text embeddings via Inference API
- Inference endpoints management

API Reference:
  Hub API: https://huggingface.co/docs/hub/api
  Inference API: https://huggingface.co/docs/api-inference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

BASE_URL = "https://huggingface.co/api"
INFERENCE_URL = "https://api-inference.huggingface.co/models"


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


def _post(
    url: str, token: str | None, payload: dict[str, Any],
    timeout: float = 120.0,
) -> dict[str, Any] | list:
    """Make a POST request to the HuggingFace Inference API."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your HUGGINGFACE_TOKEN."}
        if resp.status_code == 404:
            return {"error": f"Model not found: {url}"}
        if resp.status_code == 503:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            estimated = body.get("estimated_time", "unknown")
            return {
                "error": "Model is loading",
                "estimated_time": estimated,
                "help": "The model is being loaded. Retry after the estimated time.",
            }
        if resp.status_code != 200:
            return {"error": f"HuggingFace Inference API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Inference request timed out. Try a smaller input or a faster model."}
    except Exception as e:
        return {"error": f"HuggingFace inference request failed: {e!s}"}


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

    # -----------------------------------------------------------------
    # Inference API Tools
    # -----------------------------------------------------------------

    @mcp.tool()
    def huggingface_run_inference(
        model_id: str,
        inputs: str,
        task: str = "",
        parameters: str = "",
    ) -> dict[str, Any]:
        """
        Run inference on a HuggingFace model via the Inference API.

        Supports text-generation, summarization, translation, classification,
        fill-mask, question-answering, and more. The model's pipeline_tag
        determines the task automatically unless overridden.

        Args:
            model_id: Model ID (e.g. "meta-llama/Llama-3.1-8B-Instruct",
                      "facebook/bart-large-cnn", "distilbert-base-uncased-finetuned-sst-2-english")
            inputs: Input text for the model
            task: Optional task override (e.g. "text-generation", "summarization")
            parameters: Optional JSON string of model parameters
                        (e.g. '{"max_new_tokens": 256, "temperature": 0.7}')

        Returns:
            Dict with model output or error
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not model_id:
            return {"error": "model_id is required"}
        if not inputs:
            return {"error": "inputs is required"}

        payload: dict[str, Any] = {"inputs": inputs}

        if parameters:
            import json as _json

            try:
                payload["parameters"] = _json.loads(parameters)
            except _json.JSONDecodeError:
                return {"error": "parameters must be a valid JSON string"}

        url = f"{INFERENCE_URL}/{model_id}"
        data = _post(url, token, payload)

        if isinstance(data, dict) and "error" in data:
            return data

        return {
            "model_id": model_id,
            "task": task or "auto",
            "output": data,
        }

    @mcp.tool()
    def huggingface_run_embedding(
        model_id: str,
        inputs: str,
    ) -> dict[str, Any]:
        """
        Generate text embeddings using a HuggingFace model via the Inference API.

        Useful for semantic search, clustering, and similarity comparison.

        Args:
            model_id: Embedding model ID
                      (e.g. "sentence-transformers/all-MiniLM-L6-v2",
                       "BAAI/bge-small-en-v1.5")
            inputs: Text to embed (single string)

        Returns:
            Dict with embedding vector, model_id, and dimensions count
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not model_id:
            return {"error": "model_id is required"}
        if not inputs:
            return {"error": "inputs is required"}

        url = f"{INFERENCE_URL}/{model_id}"
        payload: dict[str, Any] = {"inputs": inputs}
        data = _post(url, token, payload)

        if isinstance(data, dict) and "error" in data:
            return data

        # Inference API returns the embedding directly as a list of floats
        # or a list of lists for batched inputs
        embedding = data if isinstance(data, list) else []
        dims = len(embedding) if embedding and isinstance(embedding[0], (int, float)) else 0

        return {
            "model_id": model_id,
            "embedding": embedding,
            "dimensions": dims,
        }

    @mcp.tool()
    def huggingface_list_inference_endpoints(
        namespace: str = "",
    ) -> dict[str, Any]:
        """
        List deployed Inference Endpoints on HuggingFace.

        Inference Endpoints are dedicated, production-ready deployments
        of HuggingFace models with autoscaling and GPU support.

        Args:
            namespace: Optional namespace/organization to filter by.
                       Defaults to the authenticated user.

        Returns:
            Dict with list of endpoints (name, model, status, url, etc.)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        path = f"/api/endpoints/{namespace}" if namespace else "/api/endpoints"
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}

        try:
            resp = httpx.get(
                f"https://api.endpoints.huggingface.cloud{path}",
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {"error": "Unauthorized. Check your HUGGINGFACE_TOKEN."}
            if resp.status_code != 200:
                return {
                    "error": f"Failed to list endpoints (HTTP {resp.status_code}): {resp.text[:500]}"
                }
            data = resp.json()
        except httpx.TimeoutException:
            return {"error": "Request to HuggingFace Endpoints API timed out"}
        except Exception as e:
            return {"error": f"Endpoints request failed: {e!s}"}

        items = data.get("items", data) if isinstance(data, dict) else data
        endpoints = []
        for ep in items if isinstance(items, list) else []:
            endpoints.append(
                {
                    "name": ep.get("name", ""),
                    "model": ep.get("model", {}).get("repository", "") if isinstance(ep.get("model"), dict) else ep.get("model", ""),
                    "status": ep.get("status", {}).get("state", "") if isinstance(ep.get("status"), dict) else ep.get("status", ""),
                    "url": ep.get("status", {}).get("url", "") if isinstance(ep.get("status"), dict) else "",
                    "type": ep.get("type", ""),
                    "provider": ep.get("provider", {}).get("vendor", "") if isinstance(ep.get("provider"), dict) else "",
                    "region": ep.get("provider", {}).get("region", "") if isinstance(ep.get("provider"), dict) else "",
                }
            )
        return {"endpoints": endpoints, "count": len(endpoints)}
