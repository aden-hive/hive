from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.tools.shortcut_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with tools registered."""
    server = FastMCP("test")
    # Register without credentials for basic structure tests
    register_tools(server)
    return server


@pytest.fixture
def mcp_with_creds():
    """Create a FastMCP instance with mocked credentials."""
    server = FastMCP("test")
    creds = CredentialStoreAdapter.for_testing({"shortcut_api": "test-token"})
    register_tools(server, credentials=creds)
    return server


def test_tool_registration(mcp):
    """Test that tools are registered correctly."""
    tools = mcp._tool_manager._tools
    assert "create_shortcut_story" in tools
    assert "search_shortcut_stories" in tools


@patch("aden_tools.tools.shortcut_tool.shortcut_tool.httpx.AsyncClient")
async def test_create_story(mock_client, mcp_with_creds):
    """Test creating a story with mocked API response."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": 123, "name": "Test Story"}
    mock_response.raise_for_status.return_value = None
    
    # Setup mock client context manager
    mock_instance = mock_client.return_value
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.post.return_value = mock_response

    # Call tool
    tool_fn = mcp_with_creds._tool_manager._tools["create_shortcut_story"].fn
    result = await tool_fn(name="Test Story", description="Desc")

    # Verify
    assert result == {"id": 123, "name": "Test Story"}
    mock_instance.post.assert_called_once()
    args, kwargs = mock_instance.post.call_args
    assert kwargs["json"]["name"] == "Test Story"
    assert kwargs["headers"]["Shortcut-Token"] == "test-token"


@patch("aden_tools.tools.shortcut_tool.shortcut_tool.httpx.AsyncClient")
async def test_search_stories(mock_client, mcp_with_creds):
    """Test searching stories."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": 1, "name": "Story 1"}]}
    mock_response.raise_for_status.return_value = None
    
    mock_instance = mock_client.return_value
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.get.return_value = mock_response

    tool_fn = mcp_with_creds._tool_manager._tools["search_shortcut_stories"].fn
    result = await tool_fn(query="owner:me")

    assert result == {"data": [{"id": 1, "name": "Story 1"}]}
    mock_instance.get.assert_called_once()
    args, kwargs = mock_instance.get.call_args
    assert kwargs["params"]["query"] == "owner:me"


async def test_missing_credentials(mcp):
    """Test error when credentials are missing."""
    # Ensure env var is not set
    with patch("os.getenv", return_value=None):
        tool_fn = mcp._tool_manager._tools["create_shortcut_story"].fn
        result = await tool_fn(name="Fail")
        assert "error" in result
        assert "SHORTCUT_API_TOKEN" in result["error"]
