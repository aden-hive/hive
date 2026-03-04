"""Tests for notion_tool - Pages, databases, and search."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.notion_tool.notion_tool import register_tools

ENV = {"NOTION_API_TOKEN": "test-token"}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestNotionSearch:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_search"]()
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "results": [
                {
                    "object": "page",
                    "id": "page-1",
                    "url": "https://notion.so/page-1",
                    "created_time": "2024-01-01T00:00:00Z",
                    "last_edited_time": "2024-01-15T00:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"text": {"content": "My Page"}}],
                        }
                    },
                }
            ],
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.notion_tool.notion_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["notion_search"](query="My Page")

        assert result["count"] == 1
        assert result["results"][0]["title"] == "My Page"


class TestNotionGetPage:
    def test_missing_page_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_page"](page_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "archived": False,
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"text": {"content": "Test Page"}}],
                },
                "Status": {
                    "type": "select",
                    "select": {"name": "Done"},
                },
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.notion_tool.notion_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["notion_get_page"](page_id="page-1")

        assert result["title"] == "Test Page"
        assert result["properties"]["Status"] == "Done"


class TestNotionCreatePage:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](parent_database_id="", title="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {"id": "new-page", "url": "https://notion.so/new-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.notion_tool.notion_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["notion_create_page"](parent_database_id="db-1", title="New Page")

        assert result["status"] == "created"
        assert result["id"] == "new-page"


class TestNotionQueryDatabase:
    def test_missing_database_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_query_database"](database_id="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        data = {
            "results": [
                {
                    "id": "row-1",
                    "url": "https://notion.so/row-1",
                    "created_time": "2024-01-01T00:00:00Z",
                    "last_edited_time": "2024-01-15T00:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"text": {"content": "Task 1"}}],
                        }
                    },
                }
            ],
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.notion_tool.notion_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["notion_query_database"](database_id="db-1")

        assert result["count"] == 1
        assert result["pages"][0]["title"] == "Task 1"


class TestNotionGetDatabase:
    def test_missing_database_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_database"](database_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "db-1",
            "title": [{"text": {"content": "Tasks"}}],
            "url": "https://notion.so/db-1",
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "properties": {
                "Name": {"type": "title", "id": "title"},
                "Status": {"type": "select", "id": "abc"},
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.notion_tool.notion_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["notion_get_database"](database_id="db-1")

        assert result["title"] == "Tasks"
        assert "Name" in result["properties"]
