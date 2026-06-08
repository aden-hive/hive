"""
Apify Tool - Web scraping and automation platform.

Supports:
- Apify API token (APIFY_API_TOKEN)
- Running Actors, checking run status, retrieving datasets
- Managing key-value stores and schedules

API Reference: https://docs.apify.com/api/v2
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

APIFY_API = "https://api.apify.com/v2"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("apify")
    return os.getenv("APIFY_API_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{APIFY_API}/{endpoint}", headers=_headers(token), params=params, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your APIFY_API_TOKEN."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code != 200:
            return {"error": f"Apify API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Apify timed out"}
    except Exception as e:
        return {"error": f"Apify request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(f"{APIFY_API}/{endpoint}", headers=_headers(token), json=body or {}, timeout=60.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your APIFY_API_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Apify API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Apify timed out"}
    except Exception as e:
        return {"error": f"Apify request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "APIFY_API_TOKEN not set",
        "help": "Get your token at https://console.apify.com/account/integrations",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Apify tools with the MCP server."""

    @mcp.tool()
    def apify_run_actor(
        actor_id: str,
        input_data: dict[str, Any] | None = None,
        memory_mbytes: int = 0,
        timeout_secs: int = 0,
        build: str = "",
    ) -> dict[str, Any]:
        """
        Run an Apify Actor with optional input.

        Args:
            actor_id: Actor ID or name (e.g. "apify/web-scraper")
            input_data: Input JSON for the Actor (optional)
            memory_mbytes: Memory allocation in MB (optional, 0 = default)
            timeout_secs: Timeout in seconds (optional, 0 = default)
            build: Specific build tag (optional)

        Returns:
            Dict with run id, status, datasetId, defaultKeyValueStoreId
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not actor_id:
            return {"error": "actor_id is required"}

        params: dict[str, Any] = {}
        if memory_mbytes:
            params["memory"] = memory_mbytes
        if timeout_secs:
            params["timeout"] = timeout_secs
        if build:
            params["build"] = build

        # Build the URL with query params
        url = f"acts/{actor_id}/runs"
        try:
            resp = httpx.post(
                f"{APIFY_API}/{url}",
                headers=_headers(token),
                params=params,
                json=input_data or {},
                timeout=60.0,
            )
            if resp.status_code == 401:
                return {"error": "Unauthorized. Check your APIFY_API_TOKEN."}
            if resp.status_code not in (200, 201):
                return {"error": f"Apify API error {resp.status_code}: {resp.text[:500]}"}
            data = resp.json().get("data", {})
        except httpx.TimeoutException:
            return {"error": "Request to Apify timed out"}
        except Exception as e:
            return {"error": f"Apify request failed: {e!s}"}

        return {
            "run_id": data.get("id", ""),
            "status": data.get("status", ""),
            "dataset_id": data.get("defaultDatasetId", ""),
            "kv_store_id": data.get("defaultKeyValueStoreId", ""),
            "started_at": data.get("startedAt", ""),
        }

    @mcp.tool()
    def apify_get_run(
        actor_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """
        Get status and details of an Actor run.

        Args:
            actor_id: Actor ID or name
            run_id: Run ID to check

        Returns:
            Dict with run status, timing, resource usage, and dataset info
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not actor_id or not run_id:
            return {"error": "actor_id and run_id are required"}

        data = _get(f"acts/{actor_id}/runs/{run_id}", token)
        if "error" in data:
            return data

        run = data.get("data", {})
        usage = run.get("usage", {})
        return {
            "run_id": run.get("id", ""),
            "status": run.get("status", ""),
            "started_at": run.get("startedAt", ""),
            "finished_at": run.get("finishedAt", ""),
            "dataset_id": run.get("defaultDatasetId", ""),
            "kv_store_id": run.get("defaultKeyValueStoreId", ""),
            "usage_usd": usage.get("ACTOR_COMPUTE_UNITS", 0),
        }

    @mcp.tool()
    def apify_get_dataset_items(
        dataset_id: str,
        limit: int = 100,
        offset: int = 0,
        format: str = "json",
    ) -> dict[str, Any]:
        """
        Retrieve items from an Apify dataset (Actor output).

        Args:
            dataset_id: Dataset ID
            limit: Number of items (1-250000, default 100)
            offset: Pagination offset (default 0)
            format: Output format: json, csv, xlsx, xml, rss (default json)

        Returns:
            Dict with items list and count
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not dataset_id:
            return {"error": "dataset_id is required"}

        params = {
            "limit": max(1, min(limit, 250000)),
            "offset": offset,
            "format": format,
        }
        try:
            resp = httpx.get(
                f"{APIFY_API}/datasets/{dataset_id}/items",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            if resp.status_code != 200:
                return {"error": f"Apify API error {resp.status_code}: {resp.text[:500]}"}
            items = resp.json()
        except httpx.TimeoutException:
            return {"error": "Request to Apify timed out"}
        except Exception as e:
            return {"error": f"Apify request failed: {e!s}"}

        if isinstance(items, list):
            return {"items": items, "count": len(items)}
        return {"items": [items], "count": 1}

    @mcp.tool()
    def apify_list_actors(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List Actors in your Apify account.

        Args:
            limit: Number of results (1-1000, default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with actors list (id, name, title, description, stats)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {"limit": max(1, min(limit, 1000)), "offset": offset}
        data = _get("acts", token, params)
        if "error" in data:
            return data

        actors = []
        for a in data.get("data", {}).get("items", []):
            stats = a.get("stats", {})
            actors.append(
                {
                    "id": a.get("id", ""),
                    "name": a.get("name", ""),
                    "title": a.get("title", ""),
                    "description": (a.get("description", "") or "")[:200],
                    "total_runs": stats.get("totalRuns", 0),
                }
            )
        return {"actors": actors, "count": len(actors)}

    @mcp.tool()
    def apify_list_runs(
        actor_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List recent Actor runs.

        Args:
            actor_id: Actor ID to filter by (optional, empty = all runs)
            limit: Number of results (1-1000, default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with runs list (run_id, actor_id, status, started, finished)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {"limit": max(1, min(limit, 1000)), "offset": offset}
        endpoint = f"acts/{actor_id}/runs" if actor_id else "actor-runs"
        data = _get(endpoint, token, params)
        if "error" in data:
            return data

        runs = []
        for r in data.get("data", {}).get("items", []):
            runs.append(
                {
                    "run_id": r.get("id", ""),
                    "actor_id": r.get("actId", ""),
                    "status": r.get("status", ""),
                    "started_at": r.get("startedAt", ""),
                    "finished_at": r.get("finishedAt", ""),
                    "dataset_id": r.get("defaultDatasetId", ""),
                }
            )
        return {"runs": runs, "count": len(runs)}

    @mcp.tool()
    def apify_get_kv_store_record(
        store_id: str,
        key: str,
    ) -> dict[str, Any]:
        """
        Get a record from an Apify key-value store.

        Args:
            store_id: Key-value store ID
            key: Record key to retrieve

        Returns:
            Dict with the record value (JSON parsed if possible)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not store_id or not key:
            return {"error": "store_id and key are required"}

        try:
            resp = httpx.get(
                f"{APIFY_API}/key-value-stores/{store_id}/records/{key}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
            if resp.status_code == 404:
                return {"error": f"Key '{key}' not found in store {store_id}"}
            if resp.status_code != 200:
                return {"error": f"Apify API error {resp.status_code}: {resp.text[:500]}"}
            try:
                return {"key": key, "value": resp.json()}
            except Exception:
                text = resp.text[:5000]
                return {"key": key, "value": text}
        except httpx.TimeoutException:
            return {"error": "Request to Apify timed out"}
        except Exception as e:
            return {"error": f"Apify request failed: {e!s}"}
