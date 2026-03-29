"""Tests for SerpAPI tools (Google Scholar & Patents) - FastMCP."""

from unittest.mock import patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.serpapi_tool import register_tools


@pytest.fixture
def scholar_search_fn(mcp: FastMCP):
    """Register and return the scholar_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["scholar_search"].fn


@pytest.fixture
def scholar_cite_fn(mcp: FastMCP):
    """Register and return the scholar_get_citations tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["scholar_get_citations"].fn


@pytest.fixture
def scholar_author_fn(mcp: FastMCP):
    """Register and return the scholar_get_author tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["scholar_get_author"].fn


@pytest.fixture
def patents_search_fn(mcp: FastMCP):
    """Register and return the patents_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["patents_search"].fn


@pytest.fixture
def patents_details_fn(mcp: FastMCP):
    """Register and return the patents_get_details tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["patents_get_details"].fn


# ---- Credential Tests ----


class TestCredentials:
    """Test credential handling for all SerpAPI tools."""

    def test_scholar_search_no_creds(self, scholar_search_fn, monkeypatch):
        """scholar_search without credentials returns helpful error."""
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        result = scholar_search_fn(query="machine learning")
        assert "error" in result
        assert "SerpAPI credentials not configured" in result["error"]
        assert "help" in result

    def test_scholar_cite_no_creds(self, scholar_cite_fn, monkeypatch):
        """scholar_get_citations without credentials returns error."""
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        result = scholar_cite_fn(result_id="abc123")
        assert "error" in result
        assert "SerpAPI credentials not configured" in result["error"]

    def test_scholar_author_no_creds(self, scholar_author_fn, monkeypatch):
        """scholar_get_author without credentials returns error."""
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        result = scholar_author_fn(author_id="WLN3QrAAAAAJ")
        assert "error" in result
        assert "SerpAPI credentials not configured" in result["error"]

    def test_patents_search_no_creds(self, patents_search_fn, monkeypatch):
        """patents_search without credentials returns error."""
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        result = patents_search_fn(query="neural network")
        assert "error" in result
        assert "SerpAPI credentials not configured" in result["error"]

    def test_patents_details_no_creds(self, patents_details_fn, monkeypatch):
        """patents_get_details without credentials returns error."""
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        result = patents_details_fn(patent_id="US20210012345A1")
        assert "error" in result
        assert "SerpAPI credentials not configured" in result["error"]


# ---- Input Validation Tests ----


class TestInputValidation:
    """Test input validation for all tools."""

    def test_scholar_empty_query(self, scholar_search_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = scholar_search_fn(query="")
        assert "error" in result
        assert "1-500" in result["error"]

    def test_scholar_long_query(self, scholar_search_fn, monkeypatch):
        """Query exceeding 500 chars returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = scholar_search_fn(query="x" * 501)
        assert "error" in result
        assert "1-500" in result["error"]

    def test_cite_empty_result_id(self, scholar_cite_fn, monkeypatch):
        """Empty result_id returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = scholar_cite_fn(result_id="")
        assert "error" in result
        assert "result_id" in result["error"]

    def test_author_empty_id(self, scholar_author_fn, monkeypatch):
        """Empty author_id returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = scholar_author_fn(author_id="")
        assert "error" in result
        assert "author_id" in result["error"]

    def test_patents_empty_query(self, patents_search_fn, monkeypatch):
        """Empty patent query returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = patents_search_fn(query="")
        assert "error" in result
        assert "1-500" in result["error"]

    def test_patents_long_query(self, patents_search_fn, monkeypatch):
        """Patent query exceeding 500 chars returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = patents_search_fn(query="x" * 501)
        assert "error" in result

    def test_patents_details_empty_id(self, patents_details_fn, monkeypatch):
        """Empty patent_id returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        result = patents_details_fn(patent_id="")
        assert "error" in result
        assert "patent_id" in result["error"]


# ---- HTTP Error Handling Tests ----


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    """Create a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://serpapi.com/search.json"),
    )
    return resp


class TestHTTPErrors:
    """Test HTTP error handling."""

    def test_401_returns_auth_error(self, scholar_search_fn, monkeypatch):
        """HTTP 401 returns invalid API key error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "bad-key")
        with patch("httpx.get", return_value=_mock_response(401, {"error": "Invalid API key"})):
            result = scholar_search_fn(query="test")
        assert "error" in result
        assert "Invalid SerpAPI API key" in result["error"]

    def test_429_returns_rate_limit(self, scholar_search_fn, monkeypatch):
        """HTTP 429 returns rate limit error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(429)):
            result = scholar_search_fn(query="test")
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    def test_500_returns_server_error(self, patents_search_fn, monkeypatch):
        """HTTP 500 returns server error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(500, text="Internal Server Error")):
            result = patents_search_fn(query="test")
        assert "error" in result
        assert "500" in result["error"]

    def test_timeout_returns_error(self, scholar_search_fn, monkeypatch):
        """Timeout returns error dict."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            result = scholar_search_fn(query="test")
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_network_error_returns_error(self, scholar_search_fn, monkeypatch):
        """Network error returns error dict."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch(
            "httpx.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = scholar_search_fn(query="test")
        assert "error" in result
        assert "Network error" in result["error"] or "error" in result["error"].lower()


# ---- Success Response Tests ----


SCHOLAR_RESPONSE = {
    "search_information": {"total_results": 1000},
    "organic_results": [
        {
            "position": 0,
            "title": "Deep learning",
            "result_id": "vhbKQo7YFEEJ",
            "link": "https://www.nature.com/articles/nature14539",
            "snippet": "Deep learning allows computational models...",
            "publication_info": {
                "summary": "Y LeCun, Y Bengio, G Hinton - nature, 2015",
                "authors": [
                    {"name": "Y LeCun", "author_id": "WLN3QrAAAAAJ"},
                    {"name": "Y Bengio", "author_id": "kukA0LcAAAAJ"},
                ],
            },
            "inline_links": {
                "cited_by": {
                    "total": 75000,
                    "cites_id": "17291221010185025511",
                },
            },
            "resources": [{"title": "PDF", "link": "https://example.com/paper.pdf"}],
        }
    ],
}

CITE_RESPONSE = {
    "citations": [
        {"title": "MLA", "snippet": "LeCun, Yann, et al..."},
        {"title": "APA", "snippet": "LeCun, Y., Bengio, Y..."},
    ],
    "links": [
        {"name": "BibTeX", "link": "https://scholar.google.com/bibtex"},
    ],
}

AUTHOR_RESPONSE = {
    "author": {
        "name": "Yann LeCun",
        "affiliations": "NYU & Meta",
        "email": "Verified email at fb.com",
        "interests": [{"title": "machine learning"}, {"title": "deep learning"}],
        "thumbnail": "https://example.com/photo.jpg",
    },
    "articles": [
        {
            "title": "Gradient-based learning",
            "authors": "Y LeCun, L Bottou",
            "publication": "Proceedings of the IEEE, 1998",
            "year": "1998",
            "cited_by": {"value": 45000},
            "citation_id": "WLN3QrAAAAAJ:u5HHmVD_uO8C",
        }
    ],
    "cited_by": {
        "table": [
            {"citations": {"all": 390000, "since_2019": 200000}},
            {"h_index": {"all": 165, "since_2019": 120}},
            {"i10_index": {"all": 420, "since_2019": 350}},
        ],
    },
}

PATENT_RESPONSE = {
    "search_information": {"total_results": 500},
    "organic_results": [
        {
            "title": "Machine learning model for prediction",
            "snippet": "A system and method...",
            "link": "https://patents.google.com/patent/US20210012345A1",
            "patent_id": "US20210012345A1",
            "publication_number": "US20210012345A1",
            "inventor": "John Smith",
            "assignee": "Google LLC",
            "filing_date": "2020-07-10",
            "grant_date": None,
            "publication_date": "2021-01-14",
            "priority_date": "2020-07-10",
            "pdf": "https://example.com/patent.pdf",
        }
    ],
}


class TestScholarSearch:
    """Tests for scholar_search with mock API responses."""

    def test_successful_search(self, scholar_search_fn, monkeypatch):
        """Successful scholar search returns structured results."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, SCHOLAR_RESPONSE)):
            result = scholar_search_fn(query="deep learning")

        assert "error" not in result
        assert result["query"] == "deep learning"
        assert result["total_results"] == 1000
        assert result["count"] == 1
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Deep learning"
        assert paper["result_id"] == "vhbKQo7YFEEJ"
        assert paper["cited_by_count"] == 75000
        assert paper["cites_id"] == "17291221010185025511"
        assert paper["pdf_link"] == "https://example.com/paper.pdf"
        assert len(paper["authors"]) == 2
        assert paper["authors"][0]["name"] == "Y LeCun"

    def test_search_with_year_filter(self, scholar_search_fn, monkeypatch):
        """Search with year filters works."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, SCHOLAR_RESPONSE)) as mock:
            scholar_search_fn(query="AI", year_low=2020, year_high=2024)
            params = mock.call_args[1]["params"]
            assert params["as_ylo"] == 2020
            assert params["as_yhi"] == 2024


class TestScholarCite:
    """Tests for scholar_get_citations with mock API responses."""

    def test_successful_cite(self, scholar_cite_fn, monkeypatch):
        """Successful citation lookup returns formats."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, CITE_RESPONSE)):
            result = scholar_cite_fn(result_id="vhbKQo7YFEEJ")

        assert "error" not in result
        assert result["result_id"] == "vhbKQo7YFEEJ"
        assert len(result["citations"]) == 2
        assert result["citations"][0]["title"] == "MLA"
        assert len(result["links"]) == 1


class TestScholarAuthor:
    """Tests for scholar_get_author with mock API responses."""

    def test_successful_author(self, scholar_author_fn, monkeypatch):
        """Successful author lookup returns profile and metrics."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, AUTHOR_RESPONSE)):
            result = scholar_author_fn(author_id="WLN3QrAAAAAJ")

        assert "error" not in result
        assert result["name"] == "Yann LeCun"
        assert result["affiliations"] == "NYU & Meta"
        assert "machine learning" in result["interests"]
        assert result["metrics"]["h_index"]["all"] == 165
        assert result["article_count"] == 1
        assert result["articles"][0]["cited_by_count"] == 45000


class TestPatentsSearch:
    """Tests for patents_search with mock API responses."""

    def test_successful_search(self, patents_search_fn, monkeypatch):
        """Successful patent search returns structured results."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, PATENT_RESPONSE)):
            result = patents_search_fn(query="machine learning")

        assert "error" not in result
        assert result["total_results"] == 500
        assert result["count"] == 1
        patent = result["results"][0]
        assert patent["patent_id"] == "US20210012345A1"
        assert patent["inventor"] == "John Smith"
        assert patent["assignee"] == "Google LLC"

    def test_search_with_filters(self, patents_search_fn, monkeypatch):
        """Search with country and status filters works."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, PATENT_RESPONSE)) as mock:
            patents_search_fn(query="AI", country="US", status="GRANT")
            params = mock.call_args[1]["params"]
            assert params["country"] == "US"
            assert params["status"] == "GRANT"


class TestPatentsDetails:
    """Tests for patents_get_details with mock API responses."""

    def test_successful_details(self, patents_details_fn, monkeypatch):
        """Successful patent detail lookup."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        with patch("httpx.get", return_value=_mock_response(200, PATENT_RESPONSE)):
            result = patents_details_fn(patent_id="US20210012345A1")

        assert "error" not in result
        assert result["patent_id"] == "US20210012345A1"
        assert result["title"] == "Machine learning model for prediction"
        assert result["inventor"] == "John Smith"

    def test_not_found(self, patents_details_fn, monkeypatch):
        """Patent not found returns error."""
        monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
        empty_response = {"organic_results": []}
        with patch("httpx.get", return_value=_mock_response(200, empty_response)):
            result = patents_details_fn(patent_id="INVALID123")
        assert "error" in result
        assert "No patent found" in result["error"]
