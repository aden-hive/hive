import json
import urllib.request
from typing import Any, Dict, List

from fastmcp import FastMCP

def _fetch_json(url: str) -> Any:
    """Helper to fetch and parse JSON from a URL."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Aden-Hive-HackerNewsTool/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())

def register_tools(mcp: FastMCP) -> None:
    """Register HackerNews tools with the MCP server."""

    @mcp.tool()
    def get_top_stories(limit: int = 10) -> Dict[str, Any]:
        """
        Get the current top stories from HackerNews.
        
        Use this when you need to see what is currently trending on HackerNews.
        
        Args:
            limit: Maximum number of stories to return (1-50, default: 10)
            
        Returns:
            Dict containing the list of top story items or an error message.
        """
        if limit < 1 or limit > 50:
            limit = max(1, min(50, limit))
            
        try:
            stories_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
            story_ids = _fetch_json(stories_url)
            
            # Fetch details for the requested number of stories
            results: List[Dict[str, Any]] = []
            for item_id in story_ids[:limit]:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                item = _fetch_json(item_url)
                if item:
                    results.append(item)
                    
            return {
                "results": results,
                "total": len(results),
            }
        except Exception as e:
            return {"error": f"Failed to fetch HackerNews top stories: {str(e)}"}

    @mcp.tool()
    def get_item(item_id: int) -> Dict[str, Any]:
        """
        Get details for a specific HackerNews item (story, comment, poll, etc.) by its ID.
        
        Args:
            item_id: The numeric ID of the HackerNews item.
            
        Returns:
            Dict containing the item details or an error message.
        """
        if not isinstance(item_id, int) or item_id <= 0:
            return {"error": "Invalid item ID provided. Must be a positive integer."}
            
        try:
            item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
            item = _fetch_json(item_url)
            
            if not item:
                return {"error": f"Item {item_id} not found on HackerNews."}
                
            return {"item": item}
        except Exception as e:
            return {"error": f"Failed to fetch HackerNews item {item_id}: {str(e)}"}
