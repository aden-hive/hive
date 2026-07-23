"""Tests for hackernews_tool - HackerNews API integration."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.hackernews_tool.hackernews_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestHackerNewsTool:
    @patch("aden_tools.tools.hackernews_tool.hackernews_tool._fetch_json")
    def test_get_top_stories_success(self, mock_fetch_json, tool_fns):
        # Mocking the top stories list
        mock_fetch_json.side_effect = [
            [101, 102], # the story IDs
            {"id": 101, "title": "First Story", "url": "http://example.com/1"},
            {"id": 102, "title": "Second Story", "url": "http://example.com/2"}
        ]
        
        result = tool_fns["get_top_stories"](limit=2)
        
        assert "error" not in result
        assert result["total"] == 2
        assert result["results"][0]["id"] == 101
        assert result["results"][1]["title"] == "Second Story"

    @patch("aden_tools.tools.hackernews_tool.hackernews_tool._fetch_json")
    def test_get_top_stories_error(self, mock_fetch_json, tool_fns):
        mock_fetch_json.side_effect = Exception("Network Error")
        
        result = tool_fns["get_top_stories"](limit=5)
        
        assert "error" in result
        assert "Network Error" in result["error"]

    @patch("aden_tools.tools.hackernews_tool.hackernews_tool._fetch_json")
    def test_get_item_success(self, mock_fetch_json, tool_fns):
        mock_fetch_json.return_value = {"id": 12345, "title": "Test Item", "type": "story"}
        
        result = tool_fns["get_item"](item_id=12345)
        
        assert "error" not in result
        assert result["item"]["id"] == 12345
        assert result["item"]["title"] == "Test Item"

    def test_get_item_invalid_id(self, tool_fns):
        result = tool_fns["get_item"](item_id=-5)
        
        assert "error" in result
        assert "Invalid item ID" in result["error"]
        
    @patch("aden_tools.tools.hackernews_tool.hackernews_tool._fetch_json")
    def test_get_item_not_found(self, mock_fetch_json, tool_fns):
        mock_fetch_json.return_value = None
        
        result = tool_fns["get_item"](item_id=999999999)
        
        assert "error" in result
        assert "not found" in result["error"]
