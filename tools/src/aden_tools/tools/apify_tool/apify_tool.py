"""
Apify Tool - Universal Web Scraping & Automation via Apify Marketplace.

Supports:
- Direct API token (APIFY_API_TOKEN)
- Credential store via CredentialStoreAdapter

API Reference: https://docs.apify.com/api/v2

Tools:
- apify_run_actor: Run an actor synchronously or asynchronously
- apify_get_dataset: Retrieve dataset items from a completed run
- apify_get_run: Check status of an actor run
- apify_search_actors: Search the Apify marketplace (optional)
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

APIFY_API_BASE = "https://api.apify.com/v2"


class _ApifyClient:
    """Internal client wrapping Apify API HTTP calls."""

    def __init__(self, api_token: str):
        self._api_token = api_token
        self._headers = {"Authorization": f"Bearer {api_token}"}

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Make an HTTP request to Apify API."""
        url = f"{APIFY_API_BASE}/{endpoint}"

        try:
            response = httpx.request(
                method=method,
                url=url,
                headers=self._headers,
                params=params,
                json=json_data,
                timeout=timeout,
            )

            if response.status_code == 401:
                return {
                    "error": "Invalid Apify API token",
                    "help": "Check your token at https://console.apify.com/account/integrations",
                }
            if response.status_code == 404:
                return {
                    "error": "Resource not found (actor, run, or dataset does not exist)",
                    "help": "Verify the ID is correct",
                }
            if response.status_code == 429:
                return {"error": "Apify rate limit exceeded. Try again later."}
            if response.status_code >= 400:
                try:
                    detail = response.json().get("error", {}).get("message", response.text)
                except Exception:
                    detail = response.text
                return {"error": f"Apify API error (HTTP {response.status_code}): {detail}"}

            data = response.json()
            if "error" in data:
                return {"error": f"Apify error: {data['error']}"}
            return data

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

    def run_actor(
        self, actor_id: str, input_data: dict[str, Any], wait: bool = True, timeout: float = 120.0
    ) -> dict[str, Any]:
        """
        Run an Apify Actor.

        Args:
            actor_id: Actor identifier (e.g., "apify/instagram-scraper")
            input_data: JSON input for the actor
            wait: If True, wait for completion and return results. If False, return run_id
            timeout: Request timeout in seconds

        Returns:
            Dict with results (if wait=True) or run info (if wait=False)
        """
        if wait:
            # Synchronous execution: run and get dataset items in one request
            endpoint = f"acts/{actor_id}/run-sync-get-dataset-items"
            result = self._request("POST", endpoint, json_data=input_data, timeout=timeout)

            if "error" in result:
                return result

            # The sync endpoint returns dataset items directly
            return {
                "items": result,
                "count": len(result) if isinstance(result, list) else 0,
                "status": "SUCCEEDED",
            }
        else:
            # Asynchronous execution: start run and return run_id
            endpoint = f"acts/{actor_id}/runs"
            result = self._request("POST", endpoint, json_data=input_data, timeout=timeout)

            if "error" in result:
                return result

            run_data = result.get("data", {})
            return {
                "run_id": run_data.get("id", ""),
                "status": run_data.get("status", ""),
                "started_at": run_data.get("startedAt", ""),
                "default_dataset_id": run_data.get("defaultDatasetId", ""),
            }

    def get_dataset(self, dataset_id: str, limit: int = 1000) -> dict[str, Any]:
        """
        Retrieve items from an Apify dataset.

        Args:
            dataset_id: Dataset identifier
            limit: Maximum number of items to retrieve

        Returns:
            Dict with dataset items
        """
        endpoint = f"datasets/{dataset_id}/items"
        params = {"limit": limit}
        result = self._request("GET", endpoint, params=params)

        if "error" in result:
            return result

        # API returns items array directly
        items = result if isinstance(result, list) else []
        return {"items": items, "count": len(items)}

    def get_run(self, run_id: str) -> dict[str, Any]:
        """
        Get status and details of an actor run.

        Args:
            run_id: Run identifier

        Returns:
            Dict with run details
        """
        endpoint = f"actor-runs/{run_id}"
        result = self._request("GET", endpoint)

        if "error" in result:
            return result

        run_data = result.get("data", {})
        return {
            "run_id": run_data.get("id", ""),
            "status": run_data.get("status", ""),
            "started_at": run_data.get("startedAt", ""),
            "finished_at": run_data.get("finishedAt", ""),
            "default_dataset_id": run_data.get("defaultDatasetId", ""),
            "stats": run_data.get("stats", {}),
        }

    def search_actors(self, query: str, limit: int = 10) -> dict[str, Any]:
        """
        Search the Apify actor marketplace.

        Args:
            query: Search keywords
            limit: Maximum results to return

        Returns:
            Dict with search results
        """
        endpoint = "store"
        params = {"search": query, "limit": limit}
        result = self._request("GET", endpoint, params=params)

        if "error" in result:
            return result

        data = result.get("data", {})
        items = data.get("items", [])

        actors = []
        for item in items:
            actors.append(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "username": item.get("username", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "stats": item.get("stats", {}),
                }
            )

        return {"items": actors, "total": data.get("total", 0), "count": len(actors)}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Apify tools with the MCP server."""

    def _get_api_token() -> str | None:
        """Get Apify API token from credential store or environment."""
        if credentials is not None:
            return credentials.get("apify")
        return os.getenv("APIFY_API_TOKEN")

    def _get_client() -> _ApifyClient | dict[str, str]:
        """Get an Apify client, or return an error dict if no credentials."""
        api_token = _get_api_token()
        if not api_token:
            return {
                "error": "Apify credentials not configured",
                "help": (
                    "Set APIFY_API_TOKEN environment variable or configure "
                    "via credential store. Get a token at https://console.apify.com/account/integrations"
                ),
            }
        return _ApifyClient(api_token)

    def _validate_actor_id(actor_id: str) -> bool:
        """Validate actor ID format (owner/name, ~user/name, or ID)."""
        if not actor_id:
            return False
        # Match patterns: username/actor-name, ~username/actor-name, or actor IDs
        pattern = r"^(~?[\w-]+/[\w-]+|[\w]+)$"
        return bool(re.match(pattern, actor_id))

    @mcp.tool()
    def apify_run_actor(
        actor_id: str,
        input: dict | None = None,
        wait: bool = True,
    ) -> dict:
        """
        Run an Apify Actor to scrape or automate websites.

        Apify Actors are pre-built scrapers and automation tools. This tool
        can run them either synchronously (wait for results) or asynchronously
        (start job and check status later).

        Args:
            actor_id: Actor identifier (e.g., "apify/instagram-scraper")
            input: JSON input specific to the actor (default: {})
            wait: If True, waits for completion and returns results immediately.
                  If False, returns run_id for async status checks (default: True)

        Returns:
            Dict with results (items, status) or error dict

        Examples:
            # Synchronous (recommended for most use cases)
            result = apify_run_actor(
                actor_id="apify/instagram-profile-scraper",
                input={"usernames": ["instagram"]},
                wait=True
            )

            # Asynchronous (for long-running jobs)
            result = apify_run_actor(
                actor_id="apify/web-scraper",
                input={"startUrls": [{"url": "https://example.com"}]},
                wait=False
            )
        """
        if input is None:
            input = {}

        if not _validate_actor_id(actor_id):
            return {
                "error": "Invalid actor_id format",
                "help": 'Use format "owner/actor-name" (e.g., "apify/instagram-scraper")',
            }

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.run_actor(actor_id=actor_id, input_data=input, wait=wait)
        except Exception as e:
            return {"error": f"Failed to run actor: {e}"}

    @mcp.tool()
    def apify_get_dataset(dataset_id: str, limit: int = 1000) -> dict:
        """
        Retrieve results from a completed Apify actor run.

        Essential for asynchronous workflows where the agent starts a long job
        and checks back later for results.

        Args:
            dataset_id: Dataset identifier (from run status or run result)
            limit: Maximum number of items to return (default: 1000, max: 10000)

        Returns:
            Dict with items array and count, or error dict

        Example:
            # Get dataset from async run
            run = apify_run_actor(actor_id="...", wait=False)
            # ... wait for completion ...
            dataset = apify_get_dataset(dataset_id=run["default_dataset_id"])
        """
        if not dataset_id:
            return {"error": "dataset_id is required"}

        if limit < 1 or limit > 10000:
            return {"error": "limit must be between 1 and 10000"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_dataset(dataset_id=dataset_id, limit=limit)
        except Exception as e:
            return {"error": f"Failed to retrieve dataset: {e}"}

    @mcp.tool()
    def apify_get_run(run_id: str) -> dict:
        """
        Check the status of a specific Apify actor run.

        Use this to poll the status of an asynchronous run until it completes.

        Args:
            run_id: Run identifier (returned from apify_run_actor with wait=False)

        Returns:
            Dict with status, timestamps, and dataset_id, or error dict

        Example:
            run = apify_run_actor(actor_id="...", wait=False)
            status = apify_get_run(run_id=run["run_id"])
            print(f"Status: {status['status']}")  # RUNNING, SUCCEEDED, FAILED, etc.
        """
        if not run_id:
            return {"error": "run_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_run(run_id=run_id)
        except Exception as e:
            return {"error": f"Failed to get run status: {e}"}

    @mcp.tool()
    def apify_search_actors(query: str, limit: int = 10) -> dict:
        """
        Search the Apify marketplace for actors.

        Helps agents discover available scrapers and automation tools.

        Args:
            query: Search keywords (e.g., "instagram", "amazon", "linkedin")
            limit: Maximum results to return (default: 10, max: 100)

        Returns:
            Dict with actor search results, or error dict

        Example:
            actors = apify_search_actors(query="instagram", limit=5)
            for actor in actors["items"]:
                print(f"{actor['username']}/{actor['name']}: {actor['title']}")
        """
        if not query:
            return {"error": "query is required"}

        if limit < 1 or limit > 100:
            return {"error": "limit must be between 1 and 100"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.search_actors(query=query, limit=limit)
        except Exception as e:
            return {"error": f"Failed to search actors: {e}"}
