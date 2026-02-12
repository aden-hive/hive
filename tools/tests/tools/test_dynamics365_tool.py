"""Tests for Microsoft Dynamics 365 tools."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from fastmcp import FastMCP
from aden_tools.tools.dynamics365_tool import register_tools
from aden_tools.credentials import CredentialManager


@pytest.fixture
def mock_credentials():
    return CredentialManager.for_testing({
        "dynamics365": "tenant:client:secret:https://test.crm.dynamics.com"
    })


@pytest.fixture
def mcp():
    return FastMCP("test")


@pytest.mark.asyncio
async def test_dynamics365_registration(mcp, mock_credentials):
    register_tools(mcp, credentials=mock_credentials)
    # get_tools() returns a dict mapping name to tool object
    tools = await mcp.get_tools()
    assert "dynamics365_search_accounts" in tools


@pytest.mark.asyncio
async def test_dynamics365_client_auth():
    from aden_tools.tools.dynamics365_tool.client import Dynamics365Client
    
    client = Dynamics365Client("tenant:client:secret:https://test.crm.dynamics.com")
    
    # Use MagicMock for response because response.json() is synchronous in httpx
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "fake_token",
        "expires_in": 3600
    }
    
    # AsyncClient methods return coroutines
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        token = await client._get_token()
        assert token == "fake_token"
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_search_accounts_tool(mcp, mock_credentials):
    register_tools(mcp, credentials=mock_credentials)
    
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}
    
    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {"value": [{"name": "Account 1"}]}
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_token_resp
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_api_resp
            
            tools = await mcp.get_tools()
            search_tool = tools["dynamics365_search_accounts"]
            
            # Note: depending on fastmcp version, it might be .func or .fn
            func = getattr(search_tool, "func", getattr(search_tool, "fn", None))
            result = await func(filter="name eq 'Test'")
            
            assert result == {"value": [{"name": "Account 1"}]}
            mock_req.assert_called_once()


@pytest.mark.asyncio
async def test_create_account_tool(mcp, mock_credentials):
    register_tools(mcp, credentials=mock_credentials)
    
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}
    
    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {"accountid": "guid", "name": "New"}
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_token_resp
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_api_resp
            
            tools = await mcp.get_tools()
            create_tool = tools["dynamics365_create_account"]
            
            func = getattr(create_tool, "func", getattr(create_tool, "fn", None))
            result = await func(data={"name": "New"})
            
            assert result == {"accountid": "guid", "name": "New"}
            mock_req.assert_called_once()
            assert mock_req.call_args[1]["json"] == {"name": "New"}
            assert mock_req.call_args[0][0] == "POST"
