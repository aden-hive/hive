
import pytest
from unittest.mock import MagicMock, patch
from fastmcp import FastMCP
import json
import os

from aden_tools.tools.cloudinary_tool import register_cloudinary
from aden_tools.credentials import CredentialStoreAdapter

@pytest.fixture
def mcp():
    return FastMCP("test-server")

@pytest.fixture
def credentials():
    # Mock credentials that return a test URL
    mock_creds = MagicMock(spec=CredentialStoreAdapter)
    mock_creds.get.return_value = "cloudinary://api_key:api_secret@cloud_name"
    return mock_creds

def test_cloudinary_registration(mcp, credentials):
    register_cloudinary(mcp, credentials)
    # Check if tools are registered
    # FastMCP stores tools in mcp._tool_manager._tools
    tools = mcp._tool_manager._tools
    assert "cloudinary_upload" in tools
    assert "cloudinary_transform" in tools
    assert "cloudinary_get_asset" in tools
    assert "cloudinary_delete" in tools
    assert "cloudinary_list_assets" in tools

@patch("cloudinary.uploader.upload")
@patch("cloudinary.config")
def test_cloudinary_upload(mock_config, mock_upload, mcp, credentials):
    register_cloudinary(mcp, credentials)
    mock_upload.return_value = {"public_id": "test_id", "url": "http://test.url"}
    
    # Get the function
    upload_fn = mcp._tool_manager._tools["cloudinary_upload"].fn
    
    result = upload_fn(file_path="test.jpg", public_id="custom_id")
    
    mock_config.assert_called_once()
    mock_upload.assert_called_once()
    assert "test_id" in result
    assert "http://test.url" in result

@patch("cloudinary.utils.cloudinary_url")
@patch("cloudinary.config")
def test_cloudinary_transform(mock_config, mock_url, mcp, credentials):
    register_cloudinary(mcp, credentials)
    mock_url.return_value = ("http://transformed.url", {})
    
    transform_fn = mcp._tool_manager._tools["cloudinary_transform"].fn
    
    result = transform_fn(public_id="test_id", transformation=[{"width": 100}])
    
    mock_url.assert_called_once()
    assert "http://transformed.url" in result

@patch("cloudinary.api.resource")
@patch("cloudinary.config")
def test_cloudinary_get_asset(mock_config, mock_resource, mcp, credentials):
    register_cloudinary(mcp, credentials)
    mock_resource.return_value = {"public_id": "test_id", "format": "jpg"}
    
    get_fn = mcp._tool_manager._tools["cloudinary_get_asset"].fn
    
    result = get_fn(public_id="test_id")
    
    mock_resource.assert_called_once_with("test_id", resource_type="image", colors=False, faces=False)
    assert "jpg" in result

@patch("cloudinary.api.delete_resources")
@patch("cloudinary.config")
def test_cloudinary_delete(mock_config, mock_delete, mcp, credentials):
    register_cloudinary(mcp, credentials)
    mock_delete.return_value = {"deleted": {"test_id": "deleted"}}
    
    delete_fn = mcp._tool_manager._tools["cloudinary_delete"].fn
    
    result = delete_fn(public_ids=["test_id"])
    
    mock_delete.assert_called_once()
    assert "deleted" in result

@patch("cloudinary.api.resources")
@patch("cloudinary.config")
def test_cloudinary_list_assets(mock_config, mock_resources, mcp, credentials):
    register_cloudinary(mcp, credentials)
    mock_resources.return_value = {"resources": []}
    
    list_fn = mcp._tool_manager._tools["cloudinary_list_assets"].fn
    
    result = list_fn(max_results=5)
    
    mock_resources.assert_called_once()
    assert "resources" in result

def test_cloudinary_no_credentials(mcp):
    # Test fallback to environment variable
    with patch.dict(os.environ, {"CLOUDINARY_URL": "cloudinary://env:env@env"}):
        register_cloudinary(mcp, None)
        upload_fn = mcp._tool_manager._tools["cloudinary_upload"].fn
        
        with patch("cloudinary.uploader.upload") as mock_upload:
            mock_upload.return_value = {"status": "ok"}
            upload_fn(file_path="test.jpg")
            mock_upload.assert_called_once()
