"""Tests for confluence_tool - Confluence wiki & knowledge management."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.confluence_tool.confluence_tool import register_tools

ENV = {
    "CONFLUENCE_DOMAIN": "test.atlassian.net",
    "CONFLUENCE_EMAIL": "user@test.com",
    "CONFLUENCE_API_TOKEN": "test-token",
}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestConfluenceListSpaces:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["confluence_list_spaces"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "123",
                    "key": "DEV",
                    "name": "Development",
                    "type": "global",
                    "status": "current",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.confluence_tool.confluence_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["confluence_list_spaces"]()

        assert len(result["spaces"]) == 1
        assert result["spaces"][0]["key"] == "DEV"


class TestConfluenceListPages:
    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "title": "Getting Started",
                    "spaceId": "123",
                    "status": "current",
                    "version": {"number": 3},
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.confluence_tool.confluence_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["confluence_list_pages"](space_id="123")

        assert len(result["pages"]) == 1
        assert result["pages"][0]["title"] == "Getting Started"


class TestConfluenceGetPage:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["confluence_get_page"](page_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "id": "page-1",
            "title": "Getting Started",
            "spaceId": "123",
            "status": "current",
            "version": {"number": 3},
            "body": {"storage": {"value": "<p>Hello</p>"}},
            "createdAt": "2024-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.confluence_tool.confluence_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["confluence_get_page"](page_id="page-1")

        assert result["title"] == "Getting Started"
        assert result["body"] == "<p>Hello</p>"


class TestConfluenceCreatePage:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["confluence_create_page"](space_id="", title="", body="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {"id": "page-new", "title": "New Page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.confluence_tool.confluence_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["confluence_create_page"](space_id="123", title="New Page", body="<p>Content</p>")

        assert result["status"] == "created"


class TestConfluenceSearch:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["confluence_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Deploy Guide",
                    "excerpt": "How to deploy...",
                    "content": {"id": "page-1", "space": {"key": "DEV", "name": "Development"}},
                    "lastModified": "2024-06-01T00:00:00Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.confluence_tool.confluence_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["confluence_search"](query="deployment")

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Deploy Guide"
