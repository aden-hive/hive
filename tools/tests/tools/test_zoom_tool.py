import pytest
from unittest.mock import patch, MagicMock
from aden_tools.tools.zoom_tool.zoom_tool import create_meeting, list_meetings

# Mock the entire zoom_tool module where requests is used
@patch("aden_tools.tools.zoom_tool.zoom_tool.requests")
@patch.dict("os.environ", {
    "ZOOM_ACCOUNT_ID": "acc_123", 
    "ZOOM_CLIENT_ID": "cli_123", 
    "ZOOM_CLIENT_SECRET": "sec_123"
})
def test_create_meeting(mock_requests):
    # 1. Mock the Token Call
    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "mock_token"}
    
    # 2. Mock the Create Meeting Call
    mock_create_resp = MagicMock()
    mock_create_resp.json.return_value = {
        "join_url": "https://zoom.us/j/123",
        "id": 123456
    }
    
    # Configure side_effect to return token resp first, then create resp
    mock_requests.post.side_effect = [mock_token_resp, mock_create_resp]
    
    # Run
    result = create_meeting("Demo", "2023-10-30T10:00:00Z", 30)
    
    # Verify
    assert result["result"] == "success"
    assert result["join_url"] == "https://zoom.us/j/123"

@patch("aden_tools.tools.zoom_tool.zoom_tool.requests")
@patch.dict("os.environ", {
    "ZOOM_ACCOUNT_ID": "acc_123", 
    "ZOOM_CLIENT_ID": "cli_123", 
    "ZOOM_CLIENT_SECRET": "sec_123"
})
def test_list_meetings(mock_requests):
    # 1. Mock Token
    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "mock_token"}
    mock_requests.post.return_value = mock_token_resp
    
    # 2. Mock List
    mock_list_resp = MagicMock()
    mock_list_resp.json.return_value = {
        "meetings": [{"id": 1, "topic": "Daily Sync"}]
    }
    mock_requests.get.return_value = mock_list_resp
    
    # Run
    result = list_meetings()
    
    # Verify
    assert len(result["meetings"]) == 1
    assert result["meetings"][0]["topic"] == "Daily Sync"