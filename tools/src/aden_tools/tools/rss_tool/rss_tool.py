"""
RSS Feed Reader Tool - Parse RSS and Atom feeds.

Uses feedparser to extract structured data from feeds.
Useful for monitoring blogs, news, and status pages.
"""
from __future__ import annotations

from typing import Any, List, Dict
import feedparser
from fastmcp import FastMCP

def register_tools(mcp: FastMCP) -> None:
    """Register RSS feed tools with the MCP server."""

    @mcp.tool()
    def read_rss_feed(
        url: str,
        limit: int = 5,
        include_summary: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Parses an RSS or Atom feed and returns the latest items.
        
        Use this tool when you need to monitor a blog, news site, or status page 
        that provides an RSS/Atom feed URL.

        Args:
            url: The URL of the RSS or Atom feed to parse
            limit: Maximum number of items to return (default: 5)
            include_summary: Whether to include the summary text (default: True)

        Returns:
            List of dicts containing title, link, published date, and optional summary.
            Returns an error dict if parsing fails.
        """
        try:
            # Parse the feed
            feed = feedparser.parse(url)
            
            # Check for parsing errors (bozo exception)
            if feed.bozo:
                return [{"error": f"Failed to parse feed: {feed.bozo_exception}"}]

            results = []
            # Slice the entries to the limit
            entries = feed.entries[:limit] if limit > 0 else feed.entries

            for entry in entries:
                item = {
                    "title": getattr(entry, "title", "No Title"),
                    "link": getattr(entry, "link", ""),
                    "published": getattr(entry, "published", getattr(entry, "updated", ""))
                }
                
                if include_summary:
                    # Clean up summary (basic text only)
                    summary = getattr(entry, "summary", "")
                    # Simple truncation to avoid huge context usage
                    item["summary"] = summary[:500] + "..." if len(summary) > 500 else summary

                results.append(item)

            return results

        except Exception as e:
            return [{"error": f"Error parsing RSS feed: {str(e)}"}]