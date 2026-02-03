
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from aden_tools.tools.slack_tool.slack_tool import _SlackClient, register_tools

@pytest.fixture
def mock_slack_client():
    with patch("aden_tools.tools.slack_tool.slack_tool.WebClient") as MockWebClient:
        mock_instance = MockWebClient.return_value
        yield mock_instance

def test_slack_client_init(mock_slack_client):
    client = _SlackClient("fake-token")
    assert client.client is not None

def test_send_message(mock_slack_client):
    mock_slack_client.chat_postMessage.return_value.data = {"ok": True, "ts": "1234.5678"}
    
    client = _SlackClient("fake-token")
    response = client.send_message("channel", "hello")
    
    assert response == {"ok": True, "ts": "1234.5678"}
    mock_slack_client.chat_postMessage.assert_called_with(
        channel="channel", text="hello", thread_ts=None
    )

def test_list_channels(mock_slack_client):
    mock_slack_client.conversations_list.return_value.data = {"channels": []}
    
    client = _SlackClient("fake-token")
    response = client.list_channels(limit=10)
    
    assert response == {"channels": []}
    mock_slack_client.conversations_list.assert_called_with(
        limit=10, types="public_channel", exclude_archived=True
    )

def test_register_tools():
    mcp = MagicMock()
    # Mock CredentialsStoreAdapter as it might be typed checked
    credentials = MagicMock()
    credentials.get.return_value = "fake-token"
    
    with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "fake-token"}):
        register_tools(mcp)
        # Check if tools were registered
        # We expect 5 tools: slack_send_message, slack_list_channels, slack_get_channel_history, slack_list_users, slack_get_user
        assert mcp.tool.call_count >= 5
