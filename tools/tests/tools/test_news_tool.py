"""Tests for news tool with multi-provider support (FastMCP)."""

import time
from datetime import date as real_date

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.news_tool import news_tool, register_tools


class DummyResponse:
    """Simple mock response for httpx.get."""

    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def news_tools(mcp: FastMCP):
    """Register and return the news tool functions."""
    register_tools(mcp)
    return mcp._tool_manager._tools


class TestNewsSearch:
    """Tests for news_search tool."""

    def test_news_search_newsdata_success(self, news_tools, monkeypatch):
        """NewsData provider returns normalized results."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.delenv("FINLIGHT_API_KEY", raising=False)

        captured: dict = {}

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            captured["url"] = url
            captured["params"] = params or {}
            return DummyResponse(
                200,
                {
                    "results": [
                        {
                            "title": "Funding Round",
                            "source_id": "techcrunch",
                            "pubDate": "2026-02-01",
                            "link": "https://example.com/article",
                            "description": "A funding round was announced.",
                        }
                    ]
                },
            )

        monkeypatch.setattr(httpx, "get", mock_get)

        result = news_tools["news_search"].fn(query="funding")

        assert result["provider"] == "newsdata"
        assert result["query"] == "funding"
        assert result["total"] == 1
        assert captured["params"]["q"] == "funding"

    def test_news_search_falls_back_to_finlight(self, news_tools, monkeypatch):
        """Fallback to Finlight when NewsData returns an error."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            if "newsdata.io" in url:
                return DummyResponse(401, {})
            return DummyResponse(500, {})

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {
                    "articles": [
                        {
                            "title": "Market Update",
                            "source": "finlight",
                            "publishDate": "2026-02-02",
                            "link": "https://example.com/fin",
                            "summary": "Markets moved today.",
                        }
                    ]
                },
            )

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_search"].fn(query="markets")

        assert result["provider"] == "finlight"
        assert result["total"] == 1


class TestNewsByCompany:
    """Tests for news_by_company tool."""

    def test_news_by_company_date_filter(self, news_tools, monkeypatch):
        """news_by_company builds date filters and quoted company query."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.delenv("FINLIGHT_API_KEY", raising=False)

        class FakeDate(real_date):
            @classmethod
            def today(cls) -> real_date:
                return real_date(2026, 2, 10)

        monkeypatch.setattr(news_tool, "date", FakeDate)

        captured: dict = {}

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            captured["params"] = params or {}
            return DummyResponse(200, {"results": []})

        monkeypatch.setattr(httpx, "get", mock_get)

        result = news_tools["news_by_company"].fn(company_name="Acme", days_back=7)

        assert result["provider"] == "newsdata"
        assert captured["params"]["from_date"] == "2026-02-03"
        assert captured["params"]["to_date"] == "2026-02-10"
        assert captured["params"]["q"] == '"Acme"'


class TestRateLimiting:
    """Tests for exponential backoff on 429 responses."""

    def test_newsdata_retries_on_429_then_succeeds(self, news_tools, monkeypatch):
        """NewsData retries with backoff on 429 and succeeds on next attempt."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.delenv("FINLIGHT_API_KEY", raising=False)

        call_count = 0

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DummyResponse(429, {})
            return DummyResponse(200, {"results": [{"title": "OK", "source_id": "s"}]})

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        result = news_tools["news_search"].fn(query="test")

        assert call_count == 2
        assert result["provider"] == "newsdata"

    def test_newsdata_429_exhausts_retries_then_falls_back(self, news_tools, monkeypatch):
        """NewsData exhausts retries on 429, seamlessly falls back to Finlight."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            return DummyResponse(429, {})

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {"articles": [{"title": "Fallback", "source": "fin"}]},
            )

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(httpx, "post", mock_post)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        result = news_tools["news_search"].fn(query="test")

        assert result["provider"] == "finlight"

    def test_finlight_retries_on_429_then_succeeds(self, news_tools, monkeypatch):
        """Finlight retries with backoff on 429 and succeeds on next attempt."""
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")
        monkeypatch.delenv("NEWSDATA_API_KEY", raising=False)

        call_count = 0

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DummyResponse(429, {})
            return DummyResponse(
                200,
                {"articles": [{"title": "OK", "source": "fin", "sentiment": 0.5}]},
            )

        monkeypatch.setattr(httpx, "post", mock_post)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        result = news_tools["news_sentiment"].fn(query="test")

        assert call_count == 2
        assert result["provider"] == "finlight"


class TestSentimentNormalization:
    """Tests for sentiment score normalization."""

    def test_numeric_sentiment_passed_through(self, news_tools, monkeypatch):
        """Numeric sentiment scores are kept in [-1, 1] range."""
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {
                    "articles": [
                        {"title": "A", "source": "s", "sentiment": 0.75},
                        {"title": "B", "source": "s", "sentiment": -0.3},
                    ]
                },
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_sentiment"].fn(query="test")

        assert result["results"][0]["sentiment"] == 0.75
        assert result["results"][1]["sentiment"] == -0.3

    def test_categorical_sentiment_normalized(self, news_tools, monkeypatch):
        """Categorical labels (positive/negative/neutral) mapped to floats."""
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {
                    "articles": [
                        {"title": "A", "source": "s", "sentiment": "positive"},
                        {"title": "B", "source": "s", "sentiment": "negative"},
                        {"title": "C", "source": "s", "sentiment": "neutral"},
                    ]
                },
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_sentiment"].fn(query="test")

        assert result["results"][0]["sentiment"] == 1.0
        assert result["results"][1]["sentiment"] == -1.0
        assert result["results"][2]["sentiment"] == 0.0

    def test_out_of_range_sentiment_clamped(self, news_tools, monkeypatch):
        """Numeric scores outside [-1, 1] are clamped."""
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {"articles": [{"title": "A", "source": "s", "sentiment": 5.0}]},
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_sentiment"].fn(query="test")

        assert result["results"][0]["sentiment"] == 1.0


class TestFallbackBehavior:
    """Tests for lazy fallback and exception handling."""

    def test_finlight_not_called_when_newsdata_succeeds(self, news_tools, monkeypatch):
        """Finlight should NOT be called when NewsData succeeds (lazy fallback)."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        finlight_called = False

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            return DummyResponse(200, {"results": [{"title": "OK", "source_id": "s"}]})

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            nonlocal finlight_called
            finlight_called = True
            return DummyResponse(200, {"articles": []})

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_search"].fn(query="test")

        assert result["provider"] == "newsdata"
        assert not finlight_called, "Finlight should not be called when NewsData succeeds"

    def test_fallback_on_newsdata_timeout(self, news_tools, monkeypatch):
        """Finlight fallback should work when NewsData raises a timeout exception."""
        monkeypatch.setenv("NEWSDATA_API_KEY", "news-key")
        monkeypatch.setenv("FINLIGHT_API_KEY", "finlight-key")

        def mock_get(url: str, params=None, timeout=30.0, headers=None):
            raise httpx.ReadTimeout("Connection timed out")

        def mock_post(url: str, json=None, timeout=30.0, headers=None):
            return DummyResponse(
                200,
                {"articles": [{"title": "Fallback", "source": "fin"}]},
            )

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(httpx, "post", mock_post)

        result = news_tools["news_search"].fn(query="test")

        assert "error" not in result, f"Should fallback to Finlight, got: {result}"
        assert result["provider"] == "finlight"


class TestNewsSentiment:
    """Tests for news_sentiment tool."""

    def test_news_sentiment_requires_finlight(self, news_tools, monkeypatch):
        """news_sentiment returns error when Finlight key missing."""
        monkeypatch.delenv("FINLIGHT_API_KEY", raising=False)
        monkeypatch.delenv("NEWSDATA_API_KEY", raising=False)

        result = news_tools["news_sentiment"].fn(query="Acme")

        assert "error" in result
        assert "Finlight credentials not configured" in result["error"]
