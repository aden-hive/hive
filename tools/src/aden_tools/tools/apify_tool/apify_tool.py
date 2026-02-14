"""
Apify Tool - Universal web scraping & automation via Apify marketplace.

Supports:
- Direct API token (APIFY_API_TOKEN)
- Credential store via CredentialStoreAdapter

API Reference: https://docs.apify.com/api/v2

Tools:
- apify_run_actor: Run an Apify Actor with sync/async execution
- apify_get_dataset: Retrieve dataset items from a completed run
- apify_get_run: Check status and details of an actor run
- apify_search_actors: Search the Apify marketplace for actors
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

APIFY_BASE = "https://api.apify.com/v2"


class _ApifyClient:
    """Internal client wrapping Apify HTTP API calls."""

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
        url = f"{APIFY_BASE}/{endpoint.lstrip('/')}"

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
                    "help": (
                        "Check your token at "
                        "https://console.apify.com/account/integrations"
                    ),
                }
            if response.status_code == 404:
                return {"error": f"Resource not found: {endpoint}"}
            if response.status_code == 429:
                return {"error": "Apify rate limit exceeded. Try again later."}
            if response.status_code >= 400:
                try:
                    detail = response.json().get("error", {}).get("message", response.text)
                except Exception:
                    detail = response.text
                return {"error": f"Apify API error (HTTP {response.status_code}): {detail}"}

            return response.json()

        except httpx.TimeoutException:
            return {"error": f"Request timed out after {timeout}s"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    def run_actor_sync(
        self,
        actor_id: str,
        input_data: dict[str, Any],
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run an actor synchronously and return dataset items."""
        endpoint = f"acts/{actor_id}/run-sync-get-dataset-items"
        params = {"timeout": timeout}
        result = self._request(
            "POST", endpoint, params=params, json_data=input_data, timeout=timeout + 5
        )
        return result

    def run_actor_async(
        self,
        actor_id: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Start an actor run asynchronously and return run info."""
        endpoint = f"acts/{actor_id}/runs"
        return self._request("POST", endpoint, json_data=input_data)

    def get_dataset(
        self,
        dataset_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Retrieve dataset items."""
        endpoint = f"datasets/{dataset_id}/items"
        params = {"limit": limit, "offset": offset, "format": "json"}
        return self._request("GET", endpoint, params=params)

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Get actor run details."""
        endpoint = f"actor-runs/{run_id}"
        return self._request("GET", endpoint)

    def search_actors(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search for actors in the Apify store."""
        endpoint = "store"
        params = {"search": query, "limit": limit}
        return self._request("GET", endpoint, params=params)


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
                    "via credential store. Get a token at "
                    "https://console.apify.com/account/integrations"
                ),
            }
        return _ApifyClient(api_token)

    @mcp.tool()
    def apify_run_actor(
        actor_id: str,
        input: dict | None = None,
        wait: bool = True,
        timeout: int = 300,
    ) -> dict:
        """
        Run an Apify Actor to scrape websites or automate tasks.

        Apify provides thousands of ready-made scrapers (Actors) for specific sites
        like Instagram, Google Maps, Amazon, LinkedIn, etc. This tool lets you run
        any public Actor without writing scraping code.

        Args:
            actor_id: Full actor name (
                e.g., "apify/instagram-scraper", "apify/google-maps-scraper"
            )
            input: JSON input specific to the Actor (
                see Actor documentation for required fields
            )
            wait: If True, waits for completion and returns results (default).
                If False, returns run_id immediately.
            timeout: Maximum seconds to wait for completion when wait=True (
                default 300, max 300
            )

        Returns:
            Dict with results array (if wait=True) or run info with run_id
            (if wait=False), or error dict

        Examples:
            - Web scraper: actor_id="apify/web-scraper",
                input={"startUrls": [{"url": "https://example.com"}]}
            - Instagram: actor_id="apify/instagram-scraper",
                input={"username": "example"}
            - Google Maps: actor_id="apify/google-maps-scraper",
                input={"searchStringsArray": ["restaurants in NYC"]}
        """
        if not actor_id or not isinstance(actor_id, str):
            return {
                "error": (
                    "actor_id is required and must be a string "
                    "(e.g., 'apify/web-scraper')"
                )
            }

        if input is None:
            input = {}
        if not isinstance(input, dict):
            return {"error": "input must be a dictionary/object"}

        if timeout < 1 or timeout > 300:
            timeout = min(max(timeout, 1), 300)

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            if wait:
                # Synchronous execution with results
                data = client.run_actor_sync(actor_id, input, timeout)
                if "error" in data:
                    return data

                # Response is an array of dataset items
                if isinstance(data, list):
                    return {
                        "actor_id": actor_id,
                        "status": "SUCCEEDED",
                        "results": data,
                        "count": len(data),
                    }
                # Fallback if API returns different structure
                return {
                    "actor_id": actor_id,
                    "status": "SUCCEEDED",
                    "results": data.get("items", [data]),
                    "count": len(data.get("items", [data])),
                }
            else:
                # Asynchronous execution - return run info
                data = client.run_actor_async(actor_id, input)
                if "error" in data:
                    return data

                run_data = data.get("data", {})
                return {
                    "actor_id": actor_id,
                    "run_id": run_data.get("id"),
                    "status": run_data.get("status"),
                    "started_at": run_data.get("startedAt"),
                    "default_dataset_id": run_data.get("defaultDatasetId"),
                    "message": (
                        "Run started. Use apify_get_run to check status and "
                        "apify_get_dataset to fetch results."
                    ),
                }

        except Exception as e:
            return {"error": f"Failed to run actor: {e}"}

    @mcp.tool()
    def apify_get_dataset(
        dataset_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """
        Retrieve results from an Apify dataset.

        Essential for async workflows where you start a run with wait=False
        and check back later to fetch the results.

        Args:
            dataset_id: Dataset ID (from defaultDatasetId in run info)
            limit: Maximum number of items to return (1-1000, default 100)
            offset: Skip this many items for pagination (default 0)

        Returns:
            Dict with items array and count, or error dict
        """
        if not dataset_id:
            return {"error": "dataset_id is required"}

        if limit < 1 or limit > 1000:
            limit = min(max(limit, 1), 1000)

        if offset < 0:
            offset = 0

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            data = client.get_dataset(dataset_id, limit, offset)
            if "error" in data:
                return data

            # The response is typically an array of items
            if isinstance(data, list):
                return {
                    "dataset_id": dataset_id,
                    "items": data,
                    "count": len(data),
                    "offset": offset,
                }

            # Fallback for different response structure
            items = data.get("items", [])
            return {
                "dataset_id": dataset_id,
                "items": items,
                "count": len(items),
                "offset": offset,
                "total": data.get("total", len(items)),
            }

        except Exception as e:
            return {"error": f"Failed to fetch dataset: {e}"}

    @mcp.tool()
    def apify_get_run(run_id: str) -> dict:
        """
        Check the status and details of an Apify actor run.

        Use this to monitor async runs started with wait=False.

        Args:
            run_id: Run ID returned from apify_run_actor with wait=False

        Returns:
            Dict with run status, timestamps, stats, and dataset ID, or error dict

        Status values:
            - READY: Run is initializing
            - RUNNING: Actor is currently running
            - SUCCEEDED: Run completed successfully
            - FAILED: Run failed with error
            - ABORTED: Run was manually stopped
            - TIMED-OUT: Run exceeded time limit
        """
        if not run_id:
            return {"error": "run_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            response = client.get_run(run_id)
            if "error" in response:
                return response

            run_data = response.get("data", {})
            return {
                "run_id": run_id,
                "status": run_data.get("status"),
                "started_at": run_data.get("startedAt"),
                "finished_at": run_data.get("finishedAt"),
                "default_dataset_id": run_data.get("defaultDatasetId"),
                "stats": run_data.get("stats", {}),
                "meta": {
                    "origin": run_data.get("meta", {}).get("origin"),
                    "client_ip": run_data.get("meta", {}).get("clientIp"),
                },
                "exit_code": run_data.get("exitCode"),
            }

        except Exception as e:
            return {"error": f"Failed to get run status: {e}"}

    @mcp.tool()
    def apify_search_actors(
        query: str,
        limit: int = 10,
    ) -> dict:
        """
        Search the Apify marketplace for actors.

        Discover actors for specific tasks like scraping Instagram,
        monitoring prices, extracting emails, etc.

        Args:
            query: Search keywords (e.g., "instagram", "google maps", "email scraper")
            limit: Maximum number of results (1-50, default 10)

        Returns:
            Dict with actors array containing name, title, description,
            and stats, or error dict
        """
        if not query or len(query) > 200:
            return {"error": "Query must be 1-200 characters"}

        if limit < 1 or limit > 50:
            limit = min(max(limit, 1), 50)

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            response = client.search_actors(query, limit)
            if "error" in response:
                return response

            # Extract relevant actor information
            items = response.get("data", {}).get("items", [])
            actors = []
            for item in items[:limit]:
                actors.append(
                    {
                        "name": item.get("name"),  # Full actor ID like "apify/instagram-scraper"
                        "title": item.get("title"),
                        "description": item.get("description", "")[
                            :200
                        ],  # Truncate
                        "username": item.get("username"),
                        "stats": {
                            "runs": item.get("stats", {}).get("totalRuns", 0),
                            "users": item.get("stats", {}).get("totalUsers", 0),
                        },
                        "url": (
                            f"https://apify.com/{item.get('username')}/"
                            f"{item.get('name')}"
                        ),
                    }
                )

            return {
                "query": query,
                "actors": actors,
                "count": len(actors),
            }

        except Exception as e:
            return {"error": f"Failed to search actors: {e}"}
