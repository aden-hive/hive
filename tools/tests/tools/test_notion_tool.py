from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.notion_tool.tool import register_tools


@pytest.fixture
def mcp():
    mcp = FastMCP("test_tools")
    return mcp


@pytest.fixture
def mock_notion():
    with patch("aden_tools.tools.notion_tool.tool.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def registered_tools(mcp, mock_notion, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "test_token")
    register_tools(mcp)
    return mcp


def test_notion_search(registered_tools, mock_notion):
    mock_notion.search.return_value = {"results": [{"id": "page_1"}]}

    # Access the tool function directly from the tool manager
    notion_search = registered_tools._tool_manager._tools["notion_search"].fn
    result = notion_search(query="test")

    mock_notion.search.assert_called_once()
    assert result == {"results": [{"id": "page_1"}]}


def test_notion_get_page(registered_tools, mock_notion):
    mock_notion.pages.retrieve.return_value = {"id": "page_1", "properties": {}}
    mock_notion.blocks.children.list.return_value = {"results": []}

    notion_get_page = registered_tools._tool_manager._tools["notion_get_page"].fn
    result = notion_get_page(page_id="page_1")

    mock_notion.pages.retrieve.assert_called_with(page_id="page_1")
    mock_notion.blocks.children.list.assert_called_with(block_id="page_1", page_size=100)
    assert result["page"]["id"] == "page_1"
    assert "content" in result


def test_notion_create_page(registered_tools, mock_notion):
    mock_notion.pages.create.return_value = {"id": "new_page"}

    notion_create_page = registered_tools._tool_manager._tools["notion_create_page"].fn
    result = notion_create_page(parent_id="parent_1", title="New Page", body="Hello")

    mock_notion.pages.create.assert_called_once()
    assert result == {"id": "new_page"}

    # Verify arguments
    call_args = mock_notion.pages.create.call_args[1]
    assert call_args["parent"] == {"page_id": "parent_1"}
    assert call_args["properties"]["title"][0]["text"]["content"] == "New Page"
    assert call_args["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello"


def test_notion_append_text(registered_tools, mock_notion):
    mock_notion.blocks.children.append.return_value = {"results": [{"id": "block_1"}]}

    notion_append_text = registered_tools._tool_manager._tools["notion_append_text"].fn
    notion_append_text(page_id="page_1", text="More text")

    mock_notion.blocks.children.append.assert_called_once()
    call_args = mock_notion.blocks.children.append.call_args[1]
    assert call_args["block_id"] == "page_1"
    assert call_args["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] == "More text"
