"""
Web Search Tool - Advanced search using Brave Search API.

Features:
- Web, news, and image search
- Advanced filtering (freshness, safe search)
- Retry logic and rate limit handling
- Structured error handling
- Response caching
- Type-safe with Pydantic models
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field, validator

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager

logger = logging.getLogger(__name__)

# Enums and Models

class SearchType(str, Enum):
    """Type of search to perform."""
    WEB = "web"
    NEWS = "news"
    IMAGES = "images"


class Freshness(str, Enum):
    """Time filter for search results."""
    DAY = "pd"      # Past day
    WEEK = "pw"     # Past week
    MONTH = "pm"    # Past month
    YEAR = "py"     # Past year


class SafeSearch(str, Enum):
    """Safe search filtering level."""
    OFF = "off"
    MODERATE = "moderate"
    STRICT = "strict"


class SearchResult(BaseModel):
    """Individual search result."""
    title: str
    url: str
    snippet: str = Field(default="", alias="description")
    published_date: Optional[str] = None
    thumbnail: Optional[str] = None
    
    class Config:
        populate_by_name = True


class NewsResult(SearchResult):
    """News-specific search result."""
    source: Optional[str] = None
    age: Optional[str] = None


class ImageResult(BaseModel):
    """Image search result."""
    title: str
    url: str
    thumbnail: str
    source: str
    properties: Optional[dict[str, Any]] = None


class SearchResponse(BaseModel):
    """Structured search response."""
    query: str
    search_type: str
    results: list[SearchResult | NewsResult | ImageResult]
    total: int
    query_time_ms: Optional[int] = None
    related_searches: list[str] = Field(default_factory=list)


class SearchError(BaseModel):
    """Structured error response."""
    error: str
    error_type: Literal["api_key", "rate_limit", "validation", "network", "unknown"]
    help: Optional[str] = None
    retry_after: Optional[int] = None


# Cache Implementation

class SimpleCache:
    """Simple in-memory cache with TTL."""
    
    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            value, expires_at = self._cache[key]
            if time.time() < expires_at:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        """Cache value with TTL."""
        self._cache[key] = (value, time.time() + self._ttl)
    
    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()


# HTTP Client with Retry Logic

class BraveSearchClient:
    """Brave Search API client with retry and rate limit handling."""
    
    BASE_URL = "https://api.search.brave.com/res/v1"
    
    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        cache_ttl: int = 300,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache = SimpleCache(ttl_seconds=cache_ttl)
        self._client: Optional[httpx.Client] = None
    
    def __enter__(self):
        self._client = httpx.Client(timeout=self.timeout)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            self._client.close()
    
    def _make_request(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> httpx.Response:
        """Make HTTP request with retry logic."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use context manager.")
        
        url = f"{self.BASE_URL}/{endpoint}"
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.get(url, params=params, headers=headers)
                
                # Success
                if response.status_code == 200:
                    return response
                
                # Rate limit - exponential backoff
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(f"Rate limited. Retry after {retry_after}s")
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                
                # Other errors - don't retry
                return response
                
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
            except httpx.RequestError as e:
                last_error = e
                logger.error(f"Request error: {e}")
                break
        
        raise last_error or httpx.RequestError("Max retries exceeded")
    
    def search(
        self,
        query: str,
        search_type: SearchType = SearchType.WEB,
        num_results: int = 10,
        country: str = "us",
        freshness: Optional[Freshness] = None,
        safe_search: SafeSearch = SafeSearch.MODERATE,
    ) -> dict[str, Any]:
        """
        Perform search with caching.
        
        Returns raw API response dict.
        """
        # Check cache
        cache_key = f"{search_type}:{query}:{num_results}:{country}:{freshness}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for query: {query}")
            return cached
        
        # Build params
        params: dict[str, Any] = {
            "q": query,
            "count": num_results,
            "country": country,
            "safesearch": safe_search.value,
        }
        
        if freshness:
            params["freshness"] = freshness.value
        
        # Determine endpoint
        endpoint_map = {
            SearchType.WEB: "web/search",
            SearchType.NEWS: "news/search",
            SearchType.IMAGES: "images/search",
        }
        endpoint = endpoint_map[search_type]
        
        # Make request
        response = self._make_request(endpoint, params)
        
        # Handle errors
        if response.status_code != 200:
            return {
                "error": True,
                "status_code": response.status_code,
                "response": response.text,
            }
        
        data = response.json()
        
        # Cache successful response
        self.cache.set(cache_key, data)
        
        return data


# Tool Registration

def register_tools(
    mcp: FastMCP,
    credentials: Optional["CredentialManager"] = None,
) -> None:
    """Register enhanced web search tools with the MCP server."""
    
    def _get_api_key() -> Optional[str]:
        """Get API key from CredentialManager or environment."""
        if credentials is not None:
            return credentials.get("brave_search")
        return os.getenv("BRAVE_SEARCH_API_KEY")
    
    @mcp.tool()
    def web_search(
        query: str,
        num_results: int = 10,
        country: str = "us",
        freshness: Optional[str] = None,
        safe_search: str = "moderate",
    ) -> dict:
        """
        Search the web using Brave Search API.
        
        Enhanced with:
        - Response caching (5 min TTL)
        - Automatic retry with exponential backoff
        - Rate limit handling
        - Structured error responses
        
        Args:
            query: Search query (1-500 chars)
            num_results: Number of results (1-20)
            country: Country code (us, uk, de, etc.)
            freshness: Time filter - 'day', 'week', 'month', 'year' (optional)
            safe_search: Filter level - 'off', 'moderate', 'strict'
        
        Returns:
            SearchResponse dict or SearchError dict
        """
        # Get API key
        api_key = _get_api_key()
        if not api_key:
            return SearchError(
                error="BRAVE_SEARCH_API_KEY not configured",
                error_type="api_key",
                help="Get an API key at https://brave.com/search/api/",
            ).model_dump()
        
        # Validate inputs
        if not query or len(query) > 500:
            return SearchError(
                error="Query must be between 1-500 characters",
                error_type="validation",
            ).model_dump()
        
        num_results = max(1, min(20, num_results))
        
        # Parse freshness
        freshness_enum = None
        if freshness:
            try:
                freshness_map = {
                    "day": Freshness.DAY,
                    "week": Freshness.WEEK,
                    "month": Freshness.MONTH,
                    "year": Freshness.YEAR,
                }
                freshness_enum = freshness_map.get(freshness.lower())
            except Exception:
                pass
        
        # Parse safe search
        try:
            safe_search_enum = SafeSearch(safe_search.lower())
        except ValueError:
            safe_search_enum = SafeSearch.MODERATE
        
        # Perform search
        try:
            with BraveSearchClient(api_key, max_retries=3, cache_ttl=300) as client:
                start_time = time.time()
                data = client.search(
                    query=query,
                    search_type=SearchType.WEB,
                    num_results=num_results,
                    country=country,
                    freshness=freshness_enum,
                    safe_search=safe_search_enum,
                )
                query_time_ms = int((time.time() - start_time) * 1000)
                
                # Handle API errors
                if data.get("error"):
                    status_code = data.get("status_code", 0)
                    if status_code == 401:
                        error_type = "api_key"
                        error_msg = "Invalid API key"
                    elif status_code == 429:
                        error_type = "rate_limit"
                        error_msg = "Rate limit exceeded"
                    else:
                        error_type = "unknown"
                        error_msg = f"API request failed: HTTP {status_code}"
                    
                    return SearchError(
                        error=error_msg,
                        error_type=error_type,
                    ).model_dump()
                
                # Extract results
                results = []
                web_results = data.get("web", {}).get("results", [])
                
                for item in web_results[:num_results]:
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            description=item.get("description", ""),
                            published_date=item.get("page_age"),
                        )
                    )
                
                # Extract related searches
                related = []
                for item in data.get("query", {}).get("related_searches", []):
                    if isinstance(item, dict):
                        related.append(item.get("query", ""))
                    elif isinstance(item, str):
                        related.append(item)
                
                return SearchResponse(
                    query=query,
                    search_type="web",
                    results=results,
                    total=len(results),
                    query_time_ms=query_time_ms,
                    related_searches=related[:5],
                ).model_dump()
        
        except httpx.TimeoutException:
            return SearchError(
                error="Search request timed out after 30s",
                error_type="network",
            ).model_dump()
        except httpx.RequestError as e:
            return SearchError(
                error=f"Network error: {str(e)}",
                error_type="network",
            ).model_dump()
        except Exception as e:
            logger.exception("Unexpected error in web_search")
            return SearchError(
                error=f"Search failed: {str(e)}",
                error_type="unknown",
            ).model_dump()
    
    @mcp.tool()
    def news_search(
        query: str,
        num_results: int = 10,
        country: str = "us",
        freshness: str = "week",
    ) -> dict:
        """
        Search for news articles using Brave News Search.
        
        Args:
            query: Search query
            num_results: Number of results (1-20)
            country: Country code
            freshness: 'day', 'week', 'month' (default: week)
        
        Returns:
            SearchResponse with news results or SearchError
        """
        api_key = _get_api_key()
        if not api_key:
            return SearchError(
                error="BRAVE_SEARCH_API_KEY not configured",
                error_type="api_key",
            ).model_dump()
        
        # Parse freshness
        freshness_map = {
            "day": Freshness.DAY,
            "week": Freshness.WEEK,
            "month": Freshness.MONTH,
        }
        freshness_enum = freshness_map.get(freshness.lower(), Freshness.WEEK)
        
        try:
            with BraveSearchClient(api_key) as client:
                data = client.search(
                    query=query,
                    search_type=SearchType.NEWS,
                    num_results=num_results,
                    country=country,
                    freshness=freshness_enum,
                )
                
                if data.get("error"):
                    return SearchError(
                        error="News search failed",
                        error_type="unknown",
                    ).model_dump()
                
                # Extract news results
                results = []
                news_results = data.get("results", [])
                
                for item in news_results[:num_results]:
                    results.append(
                        NewsResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            description=item.get("description", ""),
                            source=item.get("source", {}).get("name"),
                            age=item.get("age"),
                            thumbnail=item.get("thumbnail", {}).get("src"),
                        )
                    )
                
                return SearchResponse(
                    query=query,
                    search_type="news",
                    results=results,
                    total=len(results),
                ).model_dump()
        
        except Exception as e:
            logger.exception("Error in news_search")
            return SearchError(
                error=f"News search failed: {str(e)}",
                error_type="unknown",
            ).model_dump()