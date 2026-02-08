"""
Tests for HubSpot integration tools.
"""

import hashlib
import hmac
import json
import time
import base64
from unittest.mock import MagicMock, patch

import pytest
import httpx
from fastmcp import FastMCP

from aden_tools.tools.hubspot_tool import register_tools
from aden_tools.credentials import CredentialManager

@pytest.fixture
def mcp():
    return FastMCP("test-hubspot")

@pytest.fixture
def mock_credentials():
    return CredentialManager.for_testing({
        "hubspot": "test-token",
        "hubspot_webhook_secret": "test-secret"
    })

def test_registration(mcp, mock_credentials):
    """Test that HubSpot tools are correctly registered."""
    register_tools(mcp, credentials=mock_credentials)
    
    # Check internal tool manager
    assert "hubspot_health_check" in mcp._tool_manager._tools
    assert "hubspot_webhook_verify" in mcp._tool_manager._tools
    assert "hubspot_list_webhook_subscriptions" in mcp._tool_manager._tools
    assert "hubspot_register_webhook_subscription" in mcp._tool_manager._tools

@pytest.mark.asyncio
async def test_webhook_verify_success(mcp, mock_credentials):
    """Test successful webhook signature verification."""
    register_tools(mcp, credentials=mock_credentials)
    
    # Setup test data
    request_body = json.dumps([{"subscriptionType": "contact.creation"}])
    timestamp = str(int(time.time() * 1000))
    secret = "test-secret"
    
    # Calculate expected signature
    source = request_body + timestamp
    expected_hash = hmac.new(
        secret.encode("utf-8"),
        source.encode("utf-8"),
        hashlib.sha256
    ).digest()
    signature = base64.b64encode(expected_hash).decode("utf-8")
    
    # Execute tool function directly
    fn = mcp._tool_manager._tools["hubspot_webhook_verify"].fn
    result = await fn(
        request_body=request_body,
        signature=signature,
        timestamp=timestamp
    )
    
    assert result is True

@pytest.mark.asyncio
async def test_webhook_verify_failure_bad_signature(mcp, mock_credentials):
    """Test verification failure with incorrect signature."""
    register_tools(mcp, credentials=mock_credentials)
    
    request_body = "{}"
    timestamp = str(int(time.time() * 1000))
    signature = "bad-signature"
    
    fn = mcp._tool_manager._tools["hubspot_webhook_verify"].fn
    result = await fn(
        request_body=request_body,
        signature=signature,
        timestamp=timestamp
    )
    
    assert result is False

@pytest.mark.asyncio
async def test_webhook_verify_failure_expired_timestamp(mcp, mock_credentials):
    """Test verification failure with expired timestamp."""
    register_tools(mcp, credentials=mock_credentials)
    
    request_body = "{}"
    # 10 minutes ago
    timestamp = str(int((time.time() - 600) * 1000))
    signature = "any-signature"
    
    fn = mcp._tool_manager._tools["hubspot_webhook_verify"].fn
    result = await fn(
        request_body=request_body,
        signature=signature,
        timestamp=timestamp
    )
    
    assert result is False

@pytest.mark.asyncio
async def test_hubspot_health_check_success(mcp, mock_credentials):
    """Test health check success with mocked API."""
    register_tools(mcp, credentials=mock_credentials)
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        fn = mcp._tool_manager._tools["hubspot_health_check"].fn
        result = await fn()
        
        assert "✅" in result
        mock_get.assert_called_once()
        # Verify headers
        args, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"

@pytest.mark.asyncio
async def test_hubspot_register_subscription(mcp, mock_credentials):
    """Test registering a webhook subscription."""
    register_tools(mcp, credentials=mock_credentials)
    
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "sub_123", "eventType": "contact.creation"}
        mock_post.return_value = mock_response
        
        fn = mcp._tool_manager._tools["hubspot_register_webhook_subscription"].fn
        result = await fn(app_id=123, event_type="contact.creation")
        
        assert result["id"] == "sub_123"
        mock_post.assert_called_once()
        # Verify payload
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["eventType"] == "contact.creation"
