"""Tests for knowledge_base_tool (FastMCP)."""

import pytest
from fastmcp import FastMCP

from aden_tools.tools.knowledge_base_tool import register_tools


@pytest.fixture
def mcp():
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def confluence_search_fn(mcp: FastMCP):
    """Register and return the confluence_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["confluence_search"].fn


@pytest.fixture
def confluence_get_page_fn(mcp: FastMCP):
    """Register and return the confluence_get_page tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["confluence_get_page"].fn


@pytest.fixture
def notion_search_fn(mcp: FastMCP):
    """Register and return the notion_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["notion_search"].fn


@pytest.fixture
def notion_get_page_fn(mcp: FastMCP):
    """Register and return the notion_get_page tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["notion_get_page"].fn


@pytest.fixture
def docs_search_fn(mcp: FastMCP):
    """Register and return the docs_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["docs_search"].fn


@pytest.fixture
def docs_get_page_fn(mcp: FastMCP):
    """Register and return the docs_get_page tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["docs_get_page"].fn


@pytest.fixture
def knowledge_base_list_sources_fn(mcp: FastMCP):
    """Register and return the knowledge_base_list_sources tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["knowledge_base_list_sources"].fn


class TestConfluenceCredentials:
    """Tests for Confluence credential handling."""

    def test_no_credentials_returns_error(self, confluence_search_fn, monkeypatch):
        """Search without API key returns helpful error."""
        monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
        monkeypatch.delenv("CONFLUENCE_URL", raising=False)

        result = confluence_search_fn(query="test query")

        assert "error" in result
        assert "credentials not configured" in result["error"].lower()

    def test_no_url_returns_error(self, confluence_search_fn, monkeypatch):
        """Search without URL returns helpful error."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.delenv("CONFLUENCE_URL", raising=False)

        result = confluence_search_fn(query="test query")

        assert "error" in result
        assert "URL" in result["error"]

    def test_get_page_no_credentials(self, confluence_get_page_fn, monkeypatch):
        """Get page without API key returns error."""
        monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)

        result = confluence_get_page_fn(page_id="123456")

        assert "error" in result


class TestNotionCredentials:
    """Tests for Notion credential handling."""

    def test_no_credentials_returns_error(self, notion_search_fn, monkeypatch):
        """Search without API key returns helpful error."""
        monkeypatch.delenv("NOTION_API_KEY", raising=False)

        result = notion_search_fn(query="test query")

        assert "error" in result
        assert "credentials not configured" in result["error"].lower()

    def test_get_page_no_credentials(self, notion_get_page_fn, monkeypatch):
        """Get page without API key returns error."""
        monkeypatch.delenv("NOTION_API_KEY", raising=False)

        result = notion_get_page_fn(page_id="test-page-id")

        assert "error" in result


class TestInputValidation:
    """Tests for input validation."""

    def test_confluence_empty_query(self, confluence_search_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.setenv("CONFLUENCE_URL", "https://test.atlassian.net/wiki")

        result = confluence_search_fn(query="")

        assert "error" in result

    def test_confluence_long_query(self, confluence_search_fn, monkeypatch):
        """Query exceeding 500 chars returns error."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.setenv("CONFLUENCE_URL", "https://test.atlassian.net/wiki")

        result = confluence_search_fn(query="x" * 501)

        assert "error" in result

    def test_notion_long_query(self, notion_search_fn, monkeypatch):
        """Query exceeding 200 chars returns error."""
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = notion_search_fn(query="x" * 201)

        assert "error" in result

    def test_notion_empty_page_id(self, notion_get_page_fn, monkeypatch):
        """Empty page ID returns error."""
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = notion_get_page_fn(page_id="")

        assert "error" in result

    def test_confluence_empty_page_id(self, confluence_get_page_fn, monkeypatch):
        """Empty page ID returns error."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")

        result = confluence_get_page_fn(page_id="")

        assert "error" in result

    def test_docs_empty_base_url(self, docs_search_fn):
        """Empty base URL returns error."""
        result = docs_search_fn(base_url="", query="test")

        assert "error" in result

    def test_docs_invalid_url(self, docs_search_fn):
        """Invalid URL returns error."""
        result = docs_search_fn(base_url="not-a-url", query="test")

        assert "error" in result

    def test_docs_empty_query(self, docs_search_fn):
        """Empty query returns error."""
        result = docs_search_fn(base_url="https://example.com", query="")

        assert "error" in result

    def test_docs_long_query(self, docs_search_fn):
        """Query exceeding 200 chars returns error."""
        result = docs_search_fn(base_url="https://example.com", query="x" * 201)

        assert "error" in result

    def test_docs_get_page_empty_url(self, docs_get_page_fn):
        """Empty URL returns error."""
        result = docs_get_page_fn(url="")

        assert "error" in result

    def test_docs_get_page_invalid_url(self, docs_get_page_fn):
        """Invalid URL returns error."""
        result = docs_get_page_fn(url="not-a-url")

        assert "error" in result


class TestListSources:
    """Tests for knowledge_base_list_sources tool."""

    def test_list_sources_returns_all_sources(self, knowledge_base_list_sources_fn, monkeypatch):
        """Returns all configured sources."""
        monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
        monkeypatch.delenv("NOTION_API_KEY", raising=False)

        result = knowledge_base_list_sources_fn()

        assert "sources" in result
        assert "total" in result
        assert result["total"] >= 3

        source_names = [s["name"] for s in result["sources"]]
        assert "confluence" in source_names
        assert "notion" in source_names
        assert "docs" in source_names

    def test_list_sources_shows_configuration_status(
        self, knowledge_base_list_sources_fn, monkeypatch
    ):
        """Shows which sources are configured."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.setenv("CONFLUENCE_URL", "https://test.atlassian.net/wiki")
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = knowledge_base_list_sources_fn()

        confluence = next((s for s in result["sources"] if s["name"] == "confluence"), None)
        notion = next((s for s in result["sources"] if s["name"] == "notion"), None)

        assert confluence is not None
        assert confluence["configured"] is True
        assert notion is not None
        assert notion["configured"] is True

    def test_docs_always_configured(self, knowledge_base_list_sources_fn):
        """Docs portal is always configured (no credentials needed)."""
        result = knowledge_base_list_sources_fn()

        docs = next((s for s in result["sources"] if s["name"] == "docs"), None)

        assert docs is not None
        assert docs["configured"] is True
        assert docs["credentials_required"] == []


class TestToolRegistration:
    """Tests for tool registration."""

    def test_all_tools_registered(self, mcp: FastMCP):
        """All knowledge base tools are registered."""
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        assert "confluence_search" in tools
        assert "confluence_get_page" in tools
        assert "notion_search" in tools
        assert "notion_get_page" in tools
        assert "docs_search" in tools
        assert "docs_get_page" in tools
        assert "knowledge_base_list_sources" in tools


class TestParameters:
    """Tests for tool parameters."""

    def test_notion_filter_type_parameter(self, notion_search_fn, monkeypatch):
        """filter_type parameter is accepted."""
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = notion_search_fn(query="test", filter_type="page")
        assert isinstance(result, dict)

    def test_notion_sort_direction_parameter(self, notion_search_fn, monkeypatch):
        """sort_direction parameter is accepted."""
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = notion_search_fn(query="test", sort_direction="ascending")
        assert isinstance(result, dict)

    def test_confluence_content_type_parameter(self, confluence_search_fn, monkeypatch):
        """content_type parameter is accepted."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.setenv("CONFLUENCE_URL", "https://test.atlassian.net/wiki")

        result = confluence_search_fn(query="test", content_type="page")
        assert isinstance(result, dict)

    def test_confluence_space_key_parameter(self, confluence_search_fn, monkeypatch):
        """space_key parameter is accepted."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", "test-token")
        monkeypatch.setenv("CONFLUENCE_URL", "https://test.atlassian.net/wiki")

        result = confluence_search_fn(query="test", space_key="ENG")
        assert isinstance(result, dict)

    def test_docs_search_paths_parameter(self, docs_search_fn):
        """search_paths parameter is accepted."""
        result = docs_search_fn(
            base_url="https://example.com",
            query="test",
            search_paths=["/docs/", "/api/"],
        )
        assert isinstance(result, dict)

    def test_notion_get_page_include_blocks(self, notion_get_page_fn, monkeypatch):
        """include_blocks parameter is accepted."""
        monkeypatch.setenv("NOTION_API_KEY", "test-key")

        result = notion_get_page_fn(page_id="test-id", include_blocks=True)
        assert isinstance(result, dict)
