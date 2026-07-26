import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

_HN_BASE_URL = "https://hacker-news.firebaseio.com/v0"
_MAX_WORKERS = 10


def _fetch_json(url: str) -> Any:
    """Fetch and parse JSON from a URL.

    Args:
        url: The URL to fetch JSON data from.

    Returns:
        Parsed JSON data, or None if the request fails.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Aden-Hive-HackerNewsTool/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def _fetch_item(item_id: int) -> Dict[str, Any] | None:
    """Fetch a single HackerNews item by ID, returning None on failure.

    Args:
        item_id: The numeric ID of the HackerNews item.

    Returns:
        The item dict, or None if the request fails.
    """
    try:
        url = f"{_HN_BASE_URL}/item/{item_id}.json"
        return _fetch_json(url)
    except Exception as exc:
        logger.warning("Failed to fetch HackerNews item %d: %s", item_id, exc)
        return None


def register_tools(mcp: FastMCP) -> None:
    """Register HackerNews tools with the MCP server."""

    @mcp.tool()
    def get_top_stories(limit: int = 10) -> Dict[str, Any]:
        """Get the current top stories from HackerNews.

        Fetches trending story IDs then retrieves their details concurrently.
        Individual item failures are skipped gracefully so partial results are
        always returned when at least one story succeeds.

        Use this when you need to see what is currently trending on HackerNews.

        Args:
            limit: Maximum number of stories to return (1-50, default: 10).

        Returns:
            Dict with a ``results`` list of story dicts and a ``total`` count,
            or an ``error`` key if the top-story ID list itself cannot be fetched.
        """
        limit = max(1, min(50, limit))

        try:
            story_ids = _fetch_json(f"{_HN_BASE_URL}/topstories.json")
        except Exception as exc:
            return {"error": f"Failed to fetch HackerNews top story IDs: {exc}"}

        target_ids = story_ids[:limit]

        # Fetch item details concurrently to avoid serial latency
        results: List[Dict[str, Any]] = [None] * len(target_ids)  # type: ignore[list-item]
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(target_ids))) as executor:
            future_to_idx = {
                executor.submit(_fetch_item, item_id): idx
                for idx, item_id in enumerate(target_ids)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                item = future.result()  # _fetch_item never raises
                if item:
                    results[idx] = item

        # Filter out slots where the fetch failed
        valid_results = [r for r in results if r is not None]

        return {
            "results": valid_results,
            "total": len(valid_results),
        }

    @mcp.tool()
    def get_item(item_id: int) -> Dict[str, Any]:
        """Get details for a specific HackerNews item by its ID.

        Use this to retrieve the full metadata (title, URL, score, author,
        comment count, etc.) for a story, comment, poll, or job whose ID
        was returned by ``get_top_stories`` or any other HackerNews endpoint.

        Args:
            item_id: The numeric ID of the HackerNews item.

        Returns:
            Dict with an ``item`` key containing the item data, or an ``error``
            key if the item cannot be retrieved.
        """
        if not isinstance(item_id, int) or item_id <= 0:
            return {"error": "Invalid item ID provided. Must be a positive integer."}

        try:
            item_url = f"{_HN_BASE_URL}/item/{item_id}.json"
            item = _fetch_json(item_url)

            if not item:
                return {"error": f"Item {item_id} not found on HackerNews."}

            return {"item": item}
        except Exception as exc:
            return {"error": f"Failed to fetch HackerNews item {item_id}: {exc}"}
