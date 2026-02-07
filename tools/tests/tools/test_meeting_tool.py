import pytest
from unittest.mock import MagicMock, patch
from aden_tools.tools.meeting_tool import (
    create_meeting,
    list_upcoming_meetings,
    get_meeting_details,
    update_meeting,
    delete_meeting,
    get_meeting_transcript,
)
from aden_tools.tools.meeting_tool.zoom_client import ZoomClient, ZoomAuthError

@pytest.fixture
def mock_credentials():
    with patch("aden_tools.tools.meeting_tool.CredentialManager") as MockCreds:
        creds_instance = MockCreds.return_value
        creds_instance.get.side_effect = lambda key, default=None: {
            "ZOOM_ACCOUNT_ID": "fake_acc_id",
            "ZOOM_CLIENT_ID": "fake_client_id",
            "ZOOM_CLIENT_SECRET": "fake_secret",
            "ZOOM_USER_EMAIL": "me"
        }.get(key, default)
        yield creds_instance

@pytest.fixture
def mock_zoom_client():
    with patch("aden_tools.tools.meeting_tool.ZoomClient") as MockClient:
        client_instance = MockClient.return_value
        yield client_instance

# --- Scheduling Tests ---

def test_create_meeting(mock_credentials, mock_zoom_client):
    """Test creating a meeting returns the join URL."""
    mock_zoom_client.create_meeting.return_value = {
        "id": 12345,
        "join_url": "https://zoom.us/j/12345",
        "start_time": "2024-01-01T10:00:00Z"
    }

    result = create_meeting("Demo Call", "2024-01-01T10:00:00", 30)

    mock_zoom_client.create_meeting.assert_called_once_with(
        "Demo Call", "2024-01-01T10:00:00", 30, "", "me"
    )
    assert result["join_url"] == "https://zoom.us/j/12345"

def test_list_upcoming_meetings(mock_credentials, mock_zoom_client):
    """Test listing meetings."""
    mock_zoom_client.list_meetings.return_value = [
        {"id": 1, "topic": "Daily Sync"},
        {"id": 2, "topic": "Client Demo"}
    ]

    result = list_upcoming_meetings(limit=2)

    mock_zoom_client.list_meetings.assert_called_once_with("me", limit=2)
    assert len(result) == 2
    assert result[0]["topic"] == "Daily Sync"

# --- Lifecycle Tests ---

def test_update_meeting(mock_credentials, mock_zoom_client):
    """Test updating a meeting's topic."""
    mock_zoom_client.update_meeting.return_value = {"status": "success"}

    result = update_meeting("123", topic="New Topic")

    mock_zoom_client.update_meeting.assert_called_once_with("123", topic="New Topic")
    assert result["status"] == "success"

def test_delete_meeting(mock_credentials, mock_zoom_client):
    """Test deleting a meeting."""
    mock_zoom_client.delete_meeting.return_value = {"status": "success"}

    result = delete_meeting("123")

    mock_zoom_client.delete_meeting.assert_called_once_with("123")
    assert result["status"] == "success"

# --- Intelligence Tests ---

def test_get_meeting_transcript_success(mock_credentials, mock_zoom_client):
    """Test fetching a transcript text."""
    mock_zoom_client.get_transcript_text.return_value = "SPEAKER: Hello world\nSPEAKER 2: Hi there"

    result = get_meeting_transcript("123")

    mock_zoom_client.get_transcript_text.assert_called_once_with("123")
    assert "Hello world" in result

def test_get_meeting_transcript_not_found(mock_credentials, mock_zoom_client):
    """Test handling when no transcript exists."""
    mock_zoom_client.get_transcript_text.return_value = "Transcript not available."

    result = get_meeting_transcript("999")
    
    assert result == "Transcript not available."

# --- Client Logic Tests (Testing the actual ZoomClient logic) ---

@patch("requests.Session.post")
def test_client_auth_flow(mock_post):
    """Test that the client correctly requests an OAuth token."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "fake_token",
        "expires_in": 3600
    }

    client = ZoomClient("acc_id", "client_id", "secret")
    token = client._get_token()

    assert token == "fake_token"
    
    # Corrected Assertion: Check the dictionary params, not the string representation
    args, kwargs = mock_post.call_args
    assert kwargs['params']['grant_type'] == 'account_credentials'
    assert kwargs['params']['account_id'] == 'acc_id'

@patch("requests.Session.request")
@patch("requests.Session.post")
def test_client_pagination(mock_post, mock_request):
    """Test that the client auto-paginates results."""
    # Mock Auth
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"access_token": "t", "expires_in": 3600}

    # Mock Pages
    # Page 1
    mock_request.side_effect = [
        MagicMock(status_code=200, json=lambda: {
            "meetings": [{"id": 1}], 
            "next_page_token": "page_2"
        }),
        # Page 2
        MagicMock(status_code=200, json=lambda: {
            "meetings": [{"id": 2}], 
            "next_page_token": ""
        })
    ]

    client = ZoomClient("acc", "id", "sec")
    meetings = client.list_meetings(limit=10)

    assert len(meetings) == 2
    assert meetings[0]["id"] == 1
    assert meetings[1]["id"] == 2