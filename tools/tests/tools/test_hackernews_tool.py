import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastmcp import FastMCP
from aden_tools.tools.hackernews_tool import register_tools
from aden_tools.tools.hackernews_tool.hackernews_tool import _CACHE

@pytest.fixture
def mcp():
    """Create a FastMCP instance with HackerNews tools registered."""
    server = FastMCP("test")
    register_tools(server)
    return server

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the cache before each test."""
    _CACHE.clear()
    yield

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get')
async def test_hn_get_top_stories_basic(mock_get, mcp):
    """Test basic functionality of hn_get_top_stories with caching."""
    mock_topstories_resp = MagicMock()
    mock_topstories_resp.json.return_value = [1, 2]
    
    mock_item1_resp = MagicMock()
    mock_item1_resp.json.return_value = {
        "id": 1, "title": "Test Story 1", "url": "https://test.com/1", "score": 100, "by": "user1", "time": 12345, "type": "story"
    }
    mock_item2_resp = MagicMock()
    mock_item2_resp.json.return_value = {
        "id": 2, "title": "Test Story 2", "url": "https://test.com/2", "score": 50, "by": "user2", "time": 12346, "type": "story"
    }
    
    async def side_effect(url, **kwargs):
        if "topstories.json" in str(url):
            return mock_topstories_resp
        elif "item/1.json" in str(url):
            return mock_item1_resp
        elif "item/2.json" in str(url):
            return mock_item2_resp
        raise ValueError(f"Unexpected URL: {url}")
        
    mock_get.side_effect = side_effect
    
    tool_fn = mcp._tool_manager._tools["hn_get_top_stories"].fn
    result = await tool_fn(limit=2)
    
    assert "results" in result
    assert result["total"] == 2
    assert result["results"][0]["title"] == "Test Story 1"
    assert result["results"][1]["score"] == 50

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get')
async def test_hn_get_top_stories_min_score(mock_get, mcp):
    """Test min_score filtering."""
    mock_topstories_resp = MagicMock()
    mock_topstories_resp.json.return_value = [1, 2]
    
    mock_item1_resp = MagicMock()
    mock_item1_resp.json.return_value = {
        "id": 1, "title": "Test Story 1", "score": 100, "type": "story"
    }
    mock_item2_resp = MagicMock()
    mock_item2_resp.json.return_value = {
        "id": 2, "title": "Test Story 2", "score": 20, "type": "story"
    }
    
    async def side_effect(url, **kwargs):
        if "topstories.json" in str(url):
            return mock_topstories_resp
        elif "item/1.json" in str(url):
            return mock_item1_resp
        elif "item/2.json" in str(url):
            return mock_item2_resp
            
    mock_get.side_effect = side_effect
    
    tool_fn = mcp._tool_manager._tools["hn_get_top_stories"].fn
    result = await tool_fn(limit=2, min_score=50)
    
    assert "results" in result
    assert result["total"] == 1
    assert result["results"][0]["id"] == 1

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get')
async def test_hn_search_stories(mock_get, mcp):
    """Test searching by keyword using Algolia API."""
    mock_search_resp = MagicMock()
    mock_search_resp.json.return_value = {
        "hits": [
            {
                "objectID": "123",
                "title": "LLM Agents",
                "url": "https://example.com/llm",
                "points": 500,
                "author": "ai_dev",
                "created_at_i": 1600000000
            }
        ]
    }
    mock_get.return_value = mock_search_resp
    
    tool_fn = mcp._tool_manager._tools["hn_search_stories"].fn
    result = await tool_fn(query="LLM", limit=1)
    
    assert "results" in result
    assert result["total"] == 1
    assert result["results"][0]["id"] == 123
    assert result["results"][0]["title"] == "LLM Agents"
    assert result["results"][0]["score"] == 500
    
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert "hn.algolia.com" in call_args[0][0]
    assert call_args[1]["params"]["query"] == "LLM"
    assert call_args[1]["params"]["hitsPerPage"] == 1

@pytest.mark.asyncio
async def test_hn_search_stories_empty(mcp):
    """Test validation of empty query."""
    tool_fn = mcp._tool_manager._tools["hn_search_stories"].fn
    result = await tool_fn(query="")
    
    assert "error" in result
    assert "Query cannot be empty" in result["error"]

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get')
async def test_hn_get_item_valid(mock_get, mcp):
    """Test get_item with a valid item."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "id": 999, "title": "Valid Item", "score": 100, "type": "story"
    }
    mock_get.return_value = mock_resp
    
    tool_fn = mcp._tool_manager._tools["hn_get_item"].fn
    result = await tool_fn(item_id=999)
    
    assert "result" in result
    assert result["result"]["id"] == 999
    assert result["result"]["title"] == "Valid Item"

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get')
async def test_hn_get_item_deleted(mock_get, mcp):
    """Test get_item with a deleted item."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "id": 999, "deleted": True
    }
    mock_get.return_value = mock_resp
    
    tool_fn = mcp._tool_manager._tools["hn_get_item"].fn
    result = await tool_fn(item_id=999)
    
    assert "error" in result
    assert "not found, dead, or deleted" in result["error"]
