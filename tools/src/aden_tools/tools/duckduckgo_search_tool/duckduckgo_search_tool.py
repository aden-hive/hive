"""DuckDuckGo Search Tool - Perform free web searches and news searches."""

from duckduckgo_search import DDGS
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register DuckDuckGo search tools with the MCP server."""

    @mcp.tool()
    def duckduckgo_search(query: str, max_results: int = 5) -> dict:
        """
        Search the web using DuckDuckGo. Returns a list of results with title, link, and snippet.
        SafeSearch is enabled by default.
        """
        try:
            if not query or not query.strip():
                return {"error": "query cannot be empty"}

            with DDGS() as ddgs:
                results = list(
                    ddgs.text(
                        query.strip(), max_results=max_results, backend="api", safesearch="moderate"
                    )
                )

            return {
                "success": True,
                "query": query,
                "results": results,
                "result_count": len(results),
            }

        except Exception as e:
            return {"error": f"DuckDuckGo search failed: {str(e)}"}

    @mcp.tool()
    def duckduckgo_news_search(query: str, max_results: int = 5) -> dict:
        """
        Search for news articles using DuckDuckGo. Returns a list of news results.
        SafeSearch is enabled by default.
        """
        try:
            if not query or not query.strip():
                return {"error": "query cannot be empty"}

            with DDGS() as ddgs:
                results = list(
                    ddgs.news(query.strip(), max_results=max_results, safesearch="moderate")
                )

            return {
                "success": True,
                "query": query,
                "results": results,
                "result_count": len(results),
            }

        except Exception as e:
            return {"error": f"DuckDuckGo news search failed: {str(e)}"}
