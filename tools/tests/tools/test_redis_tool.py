from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.redis_tool.redis_tool import register_tools


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture
def tools(mcp):
    """Register the tool and return the dictionary of tools."""
    mock_mcp = MagicMock()
    tool_dict = {}

    def mock_tool():
        def decorator(f):
            tool_dict[f.__name__] = f
            return f
        return decorator

    mock_mcp.tool = mock_tool
    register_tools(mock_mcp)
    return tool_dict


@pytest.mark.asyncio
async def test_redis_ping_success(tools):
    mock_client = AsyncMock()
    mock_client.ping.return_value = True
    
    with patch("aden_tools.tools.redis_tool.redis_tool.redis.from_url", return_value=mock_client):
        with patch("os.getenv", return_value="redis://localhost:6379/0"):
            result = await tools["redis_ping"]()
            assert result["success"] is True
            assert result["message"] == "PONG"


@pytest.mark.asyncio
async def test_redis_set_success(tools):
    mock_client = AsyncMock()
    mock_client.setex.return_value = True
    
    with patch("aden_tools.tools.redis_tool.redis_tool.redis.from_url", return_value=mock_client):
        with patch("os.getenv", return_value="redis://localhost:6379/0"):
            result = await tools["redis_set"](key="test_key", value="test_value", ttl_seconds=100)
            assert result["success"] is True
            assert "SUCCESS" in result["message"]
            mock_client.setex.assert_called_once_with(name="test_key", time=100, value="test_value")


@pytest.mark.asyncio
async def test_redis_get_success(tools):
    mock_client = AsyncMock()
    mock_client.get.return_value = "cached_value"
    
    with patch("aden_tools.tools.redis_tool.redis_tool.redis.from_url", return_value=mock_client):
        with patch("os.getenv", return_value="redis://localhost:6379/0"):
            result = await tools["redis_get"](key="test_key")
            assert result["success"] is True
            assert result["value"] == "cached_value"
            mock_client.get.assert_called_once_with("test_key")


@pytest.mark.asyncio
async def test_redis_get_not_found(tools):
    mock_client = AsyncMock()
    mock_client.get.return_value = None
    
    with patch("aden_tools.tools.redis_tool.redis_tool.redis.from_url", return_value=mock_client):
        with patch("os.getenv", return_value="redis://localhost:6379/0"):
            result = await tools["redis_get"](key="missing_key")
            assert result["success"] is False
            assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_redis_missing_credentials(tools):
    with patch("os.getenv", return_value=None):
        # We pass None as credentials to register_tools in the fixture, 
        # so it will look at env vars.
        result = await tools["redis_ping"]()
        assert result["success"] is False
        assert "Missing required credential" in result["error"]
