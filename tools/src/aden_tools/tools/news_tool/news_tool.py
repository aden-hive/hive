"""
News Tool - Search news using multiple providers.

Supports:
- NewsData.io (NEWSDATA_API_KEY)
- Finlight.me (FINLIGHT_API_KEY) for sentiment and optional fallback

Auto-detection: Tries NewsData first, then Finlight.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import TYPE_CHECKING

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

NEWSDATA_URL = "https://newsdata.io/api/1/news"
NEWSDATA_ARCHIVE_URL = "https://newsdata.io/api/1/archive"
FINLIGHT_URL = "https://api.finlight.me/v2/articles"


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register news tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get available news credentials."""
        if credentials is not None:
            return {
                "newsdata_api_key": credentials.get("newsdata"),
                "finlight_api_key": credentials.get("finlight"),
            }
        return {
            "newsdata_api_key": os.getenv("NEWSDATA_API_KEY"),
            "finlight_api_key": os.getenv("FINLIGHT_API_KEY"),
        }

    def _normalize_limit(limit: int | None, default: int = 10) -> int:
        """Normalize limit to a positive integer."""
        if limit is None:
            return default
        return max(limit, 1)

    def _clean_params(params: dict[str, str | int | None]) -> dict[str, str | int]:
        """Remove None/empty values from request params."""
        return {key: value for key, value in params.items() if value not in (None, "")}

    def _build_date_range(days_back: int) -> tuple[str, str]:
        """Build from/to date strings for the past N days."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)
        return start_date.isoformat(), end_date.isoformat()

    def _newsdata_error(response: httpx.Response) -> dict:
        """Map NewsData API errors to friendly messages."""
        if response.status_code == 401:
            return {"error": "Invalid NewsData API key"}
        if response.status_code == 429:
            return {"error": "NewsData rate limit exceeded. Try again later."}
        if response.status_code == 422:
            try:
                detail = response.json().get("results", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid NewsData parameters: {detail}"}
        return {"error": f"NewsData request failed: HTTP {response.status_code}"}

    def _finlight_error(response: httpx.Response) -> dict:
        """Map Finlight API errors to friendly messages."""
        if response.status_code == 401:
            return {"error": "Invalid Finlight API key"}
        if response.status_code == 429:
            return {"error": "Finlight rate limit exceeded. Try again later."}
        if response.status_code == 422:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid Finlight parameters: {detail}"}
        return {"error": f"Finlight request failed: HTTP {response.status_code}"}

    def _format_article(
        title: str,
        source: str,
        published_at: str,
        url: str,
        snippet: str,
        sentiment: str | float | None = None,
    ) -> dict:
        """Normalize an article payload."""
        payload = {
            "title": title,
            "source": source,
            "date": published_at,
            "url": url,
            "snippet": snippet,
        }
        if sentiment is not None:
            payload["sentiment"] = sentiment
        return payload

    def _parse_newsdata_results(data: dict) -> list[dict]:
        """Parse NewsData results into normalized articles."""
        raw_results = data.get("results") or []
        return [
            _format_article(
                title=item.get("title", ""),
                source=item.get("source_id", ""),
                published_at=item.get("pubDate", ""),
                url=item.get("link", ""),
                snippet=item.get("description", ""),
            )
            for item in raw_results
        ]

    def _normalize_sentiment(raw: object) -> float | str | None:
        """Normalize sentiment to a float in the range -1.0 to +1.0.

        Handles:
        - Numeric scores already in [-1, 1] range (returned as-is)
        - Categorical labels mapped to fixed values:
          positive → 1.0, negative → -1.0, neutral → 0.0
        - None / unrecognised values → None
        """
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return max(-1.0, min(1.0, float(raw)))
        if isinstance(raw, str):
            label = raw.strip().lower()
            label_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            return label_map.get(label)
        return None

    def _parse_finlight_results(
        data: dict,
        include_sentiment: bool = False,
    ) -> list[dict]:
        """Parse Finlight results into normalized articles."""
        raw_results = data.get("articles") or data.get("data") or data.get("results") or []
        results = []
        for item in raw_results:
            sentiment_value = None
            if include_sentiment:
                raw_sentiment = item.get("sentiment") or item.get("sentiment_score")
                sentiment_value = _normalize_sentiment(raw_sentiment)
            results.append(
                _format_article(
                    title=item.get("title", ""),
                    source=item.get("source", ""),
                    published_at=item.get("publishDate", "") or item.get("published_at", ""),
                    url=item.get("link", "") or item.get("url", ""),
                    snippet=item.get("summary", "") or item.get("description", ""),
                    sentiment=sentiment_value,
                )
            )
        return results

    def _search_newsdata(
        query: str | None,
        from_date: str | None,
        to_date: str | None,
        language: str | None,
        limit: int,
        sources: str | None,
        category: str | None,
        country: str | None,
        api_key: str,
    ) -> dict:
        """Search NewsData API with exponential backoff on rate limits."""
        use_archive = bool(from_date or to_date)
        url = NEWSDATA_ARCHIVE_URL if use_archive else NEWSDATA_URL
        params = _clean_params(
            {
                "apikey": api_key,
                "q": query,
                "from_date": from_date if use_archive else None,
                "to_date": to_date if use_archive else None,
                "language": language,
                "category": category,
                "country": country,
                "size": limit,
            }
        )
        if sources:
            params["sources"] = sources

        max_retries = 3
        for attempt in range(max_retries + 1):
            response = httpx.get(url, params=params, timeout=30.0)

            if response.status_code == 429 and attempt < max_retries:
                time.sleep(2**attempt)
                continue

            if response.status_code != 200:
                return _newsdata_error(response)

            break

        data = response.json()
        results = _parse_newsdata_results(data)
        return {
            "results": results,
            "total": len(results),
            "provider": "newsdata",
        }

    def _search_finlight(
        query: str | None,
        from_date: str | None,
        to_date: str | None,
        language: str | None,
        limit: int,
        sources: str | None,
        category: str | None,
        country: str | None,
        api_key: str,
        include_sentiment: bool = False,
    ) -> dict:
        """Search Finlight API."""
        if not query and category:
            query = category
        body: dict[str, object] = {
            "query": query,
            "from": from_date,
            "to": to_date,
            "language": language,
            "pageSize": limit,
            "page": 1,
        }
        if sources:
            body["sources"] = [source.strip() for source in sources.split(",") if source.strip()]
        if country:
            body["countries"] = [country.upper()]

        json_body = {k: v for k, v in body.items() if v not in (None, "", [])}
        headers = {"X-API-KEY": api_key, "Accept": "application/json"}

        max_retries = 3
        for attempt in range(max_retries + 1):
            response = httpx.post(FINLIGHT_URL, json=json_body, headers=headers, timeout=30.0)

            if response.status_code == 429 and attempt < max_retries:
                time.sleep(2**attempt)
                continue

            if response.status_code != 200:
                return _finlight_error(response)

            break

        data = response.json()
        results = _parse_finlight_results(data, include_sentiment=include_sentiment)
        return {
            "results": results,
            "total": len(results),
            "provider": "finlight",
        }

    def _try_provider(fn, **kwargs) -> dict:
        """Call a provider function, catching network exceptions as error dicts."""
        try:
            return fn(**kwargs)
        except (httpx.TimeoutException, httpx.RequestError) as e:
            return {"error": f"Network error: {e}"}

    def _search_with_fallback(
        *,
        newsdata_key: str | None,
        finlight_key: str | None,
        search_kwargs: dict,
    ) -> dict:
        """Try primary provider; fall back to secondary only on failure."""
        primary = (
            _try_provider(_search_newsdata, api_key=newsdata_key, **search_kwargs)
            if newsdata_key
            else {"error": "NewsData credentials not configured"}
        )
        if "error" not in primary:
            return primary

        if not finlight_key:
            return primary

        fallback = _try_provider(_search_finlight, api_key=finlight_key, **search_kwargs)
        if "error" not in fallback:
            return fallback

        return {
            "error": "All providers failed",
            "providers": {"primary": primary, "fallback": fallback},
        }

    @mcp.tool()
    def news_search(
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str | None = "en",
        limit: int | None = 10,
        sources: str | None = None,
        category: str | None = None,
        country: str | None = None,
    ) -> dict:
        """
        Search news articles with filters.

        Args:
            query: Search query
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            language: Language code (e.g., en)
            limit: Max number of results
            sources: Optional sources filter
            category: Optional category filter
            country: Optional country filter

        Returns:
            Dict with list of articles and provider metadata.
        """
        if not query:
            return {"error": "Query is required"}

        creds = _get_credentials()
        newsdata_key = creds["newsdata_api_key"]
        finlight_key = creds["finlight_api_key"]
        if not newsdata_key and not finlight_key:
            return {
                "error": "No news credentials configured",
                "help": "Set NEWSDATA_API_KEY or FINLIGHT_API_KEY environment variable",
            }

        limit_value = _normalize_limit(limit)

        result = _search_with_fallback(
            newsdata_key=newsdata_key,
            finlight_key=finlight_key,
            search_kwargs={
                "query": query,
                "from_date": from_date,
                "to_date": to_date,
                "language": language,
                "limit": limit_value,
                "sources": sources,
                "category": category,
                "country": country,
            },
        )
        result["query"] = query
        return result

    @mcp.tool()
    def news_headlines(
        category: str,
        country: str,
        limit: int | None = 10,
    ) -> dict:
        """
        Get top news headlines by category and country.

        Args:
            category: Category (business, tech, finance, etc.)
            country: Country code (us, uk, etc.)
            limit: Max number of results

        Returns:
            Dict with list of headline articles and provider metadata.
        """
        if not category:
            return {"error": "Category is required"}
        if not country:
            return {"error": "Country is required"}

        creds = _get_credentials()
        newsdata_key = creds["newsdata_api_key"]
        finlight_key = creds["finlight_api_key"]
        if not newsdata_key and not finlight_key:
            return {
                "error": "No news credentials configured",
                "help": "Set NEWSDATA_API_KEY or FINLIGHT_API_KEY environment variable",
            }

        limit_value = _normalize_limit(limit)

        result = _search_with_fallback(
            newsdata_key=newsdata_key,
            finlight_key=finlight_key,
            search_kwargs={
                "query": None,
                "from_date": None,
                "to_date": None,
                "language": None,
                "limit": limit_value,
                "sources": None,
                "category": category,
                "country": country,
            },
        )
        result["category"] = category
        result["country"] = country
        return result

    @mcp.tool()
    def news_by_company(
        company_name: str,
        days_back: int = 7,
        limit: int | None = 10,
        language: str | None = "en",
    ) -> dict:
        """
        Get news mentioning a specific company.

        Args:
            company_name: Company name to search for
            days_back: Days to look back (default 7)
            limit: Max number of results
            language: Language code (e.g., en)

        Returns:
            Dict with list of articles and provider metadata.
        """
        if not company_name:
            return {"error": "Company name is required"}
        if days_back < 0:
            return {"error": "days_back must be 0 or greater"}

        from_date, to_date = _build_date_range(days_back)

        creds = _get_credentials()
        newsdata_key = creds["newsdata_api_key"]
        finlight_key = creds["finlight_api_key"]
        if not newsdata_key and not finlight_key:
            return {
                "error": "No news credentials configured",
                "help": "Set NEWSDATA_API_KEY or FINLIGHT_API_KEY environment variable",
            }

        limit_value = _normalize_limit(limit)
        query = f'"{company_name}"'

        result = _search_with_fallback(
            newsdata_key=newsdata_key,
            finlight_key=finlight_key,
            search_kwargs={
                "query": query,
                "from_date": from_date,
                "to_date": to_date,
                "language": language,
                "limit": limit_value,
                "sources": None,
                "category": None,
                "country": None,
            },
        )
        result["company_name"] = company_name
        result["days_back"] = days_back
        return result

    @mcp.tool()
    def news_sentiment(
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict:
        """
        Get news with sentiment analysis (Finlight provider).

        Each article includes a normalized sentiment score from -1.0 (most
        negative) to +1.0 (most positive). Scores of 0.0 indicate neutral
        sentiment. Use these for quantitative trend analysis across articles.

        Args:
            query: Search query
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            Dict with list of articles, each containing a normalized
            ``sentiment`` float in the range [-1.0, +1.0].
        """
        if not query:
            return {"error": "Query is required"}

        creds = _get_credentials()
        finlight_key = creds["finlight_api_key"]
        if not finlight_key:
            return {
                "error": "Finlight credentials not configured",
                "help": "Set FINLIGHT_API_KEY environment variable",
            }

        try:
            result = _search_finlight(
                query=query,
                from_date=from_date,
                to_date=to_date,
                language=None,
                limit=_normalize_limit(None),
                sources=None,
                category=None,
                country=None,
                api_key=finlight_key,
                include_sentiment=True,
            )
            result["query"] = query
            return result
        except httpx.TimeoutException:
            return {"error": "News sentiment request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        except Exception as e:
            return {"error": f"News sentiment failed: {e}"}
