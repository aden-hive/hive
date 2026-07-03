import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field
from fastmcp import FastMCP

class HNItem(BaseModel):
    id: int
    title: Optional[str] = None
    url: Optional[str] = None
    score: Optional[int] = 0
    by: Optional[str] = None
    time: Optional[int] = 0
    descendants: Optional[int] = 0
    type: str = "story"
    dead: Optional[bool] = False
    deleted: Optional[bool] = False

# Simple TTL cache for top stories
_CACHE: Dict[str, tuple[float, Any]] = {}
CACHE_TTL = 120  # seconds

def _get_from_cache(key: str) -> Optional[Any]:
    if key in _CACHE:
        timestamp, data = _CACHE[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None

def _set_cache(key: str, data: Any) -> None:
    _CACHE[key] = (time.time(), data)

def normalize_story(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a HackerNews item using the Pydantic schema."""
    if not item or item.get("dead") or item.get("deleted"):
        return None
        
    hn_item = HNItem(
        id=item.get("id", item.get("objectID", 0)),
        title=item.get("title", ""),
        url=item.get("url", ""),
        score=item.get("score", item.get("points", 0)),
        by=item.get("by", item.get("author", "")),
        time=item.get("time", item.get("created_at_i", 0)),
        descendants=item.get("descendants", item.get("num_comments", 0)),
        type=item.get("type", "story"),
    )
    return hn_item.model_dump(exclude_none=True)

async def fetch_item(client: httpx.AsyncClient, item_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single item from the HN Firebase API."""
    try:
        response = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json")
        response.raise_for_status()
        data = response.json()
        return normalize_story(data) if data else None
    except httpx.RequestError:
        return None

def register_tools(mcp: FastMCP) -> None:
    """Register HackerNews tools with the MCP server."""

    @mcp.tool()
    async def hn_get_top_stories(limit: int = 10, min_score: int = 0) -> dict:
        """
        Get the top stories currently on Hacker News.
        
        Args:
            limit: Maximum number of stories to return (1-50, default 10)
            min_score: Filter out stories with fewer points than this (default 0)
            
        Returns:
            Dict containing the list of top stories or an error
        """
        limit = max(1, min(100, limit))
        
        try:
            top_ids = _get_from_cache('topstories')
            async with httpx.AsyncClient(timeout=10.0) as client:
                if not top_ids:
                    resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                    resp.raise_for_status()
                    top_ids = resp.json()
                    _set_cache('topstories', top_ids)
                
                # Fetch a larger batch if min_score is used
                fetch_limit = min(limit * 4, 200) if min_score > 0 else limit
                ids_to_fetch = top_ids[:fetch_limit]
                
                # Concurrently fetch details
                tasks = [fetch_item(client, item_id) for item_id in ids_to_fetch]
                items = await asyncio.gather(*tasks)
                
                valid_items = [item for item in items if item is not None and item.get("type") == "story"]
                if min_score > 0:
                    valid_items = [item for item in valid_items if item.get("score", 0) >= min_score]
                
                return {
                    "results": valid_items[:limit],
                    "total": len(valid_items[:limit])
                }
        except Exception as e:
            return {"error": f"Failed to fetch top stories: {str(e)}"}

    @mcp.tool()
    async def hn_search_stories(query: str, limit: int = 10) -> dict:
        """
        Search Hacker News for stories matching a keyword using the Algolia Search API.
        
        Args:
            query: The search keyword or phrase
            limit: Maximum number of results to return (1-50, default 10)
            
        Returns:
            Dict containing the matching stories or an error
        """
        if not query:
            return {"error": "Query cannot be empty"}
            
        limit = max(1, min(50, limit))
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": limit
                }
                resp = await client.get("https://hn.algolia.com/api/v1/search", params=params)
                resp.raise_for_status()
                data = resp.json()
                
                raw_hits = data.get("hits", [])
                results = [normalize_story(hit) for hit in raw_hits]
                valid_results = [r for r in results if r is not None]
                
                return {
                    "query": query,
                    "results": valid_results,
                    "total": len(valid_results)
                }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    @mcp.tool()
    async def hn_get_item(item_id: int) -> dict:
        """
        Fetch details of a specific item from Hacker News by its ID.
        
        Args:
            item_id: The ID of the Hacker News item
            
        Returns:
            Dict containing the item details or an error if not found/deleted
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                item = await fetch_item(client, item_id)
                if not item:
                    return {"error": f"Item {item_id} not found, dead, or deleted"}
                
                return {"result": item}
        except Exception as e:
            return {"error": f"Failed to fetch item {item_id}: {str(e)}"}
