import pytest
import json
from unittest.mock import Mock, patch
import httpx
from aden_tools.tools.twilio_tool import TwilioClient

@pytest.fixture
def mock_credentials():
    return {
        "sid": "ACtest",
        "token": "test_token",
        "from": "+1234567890"
    }

@pytest.fixture
def twilio_client(mock_credentials):
    return TwilioClient(mock_credentials["sid"], mock_credentials["token"])

def test_client_init(mock_credentials):
    client = TwilioClient(mock_credentials["sid"], mock_credentials["token"])
    assert client.account_sid == "ACtest"
    assert client.auth_token == "test_token"
    assert client.auth == ("ACtest", "test_token")

@patch('httpx.Client.request')
def test_send_message(mock_request, twilio_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "sid": "SM123",
        "status": "queued",
        "direction": "outbound-api"
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    result = twilio_client.send_message("+1987654321", "Hello", "+1234567890")
    
    assert result["sid"] == "SM123"
    assert result["status"] == "queued"
    mock_request.assert_called_once()
    assert mock_request.call_args[1]["data"]["To"] == "+1987654321"
    assert mock_request.call_args[1]["data"]["Body"] == "Hello"

@patch('httpx.Client.request')
def test_fetch_history(mock_request, twilio_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "messages": [
            {"sid": "SM1", "body": "Msg 1"},
            {"sid": "SM2", "body": "Msg 2"}
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    history = twilio_client.fetch_history(limit=2)
    
    assert len(history) == 2
    assert history[0]["sid"] == "SM1"
    assert mock_request.call_args[1]["params"]["PageSize"] == 2

@patch('httpx.Client.request')
def test_validate_number(mock_request, twilio_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "phone_number": "+1234567890",
        "valid": True,
        "line_type_intelligence": {"carrier_name": "Twilio Wireless", "type": "mobile"}
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    info = twilio_client.validate_number("+1234567890")
    
    assert info["valid"] is True
    assert info["phone_number"] == "+1234567890"

@patch('httpx.Client.request')
def test_twilio_error_handling(mock_request, twilio_client):
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"message": "Authenticate"}
    mock_response.headers = {"Content-Type": "application/json"}
    
    error = httpx.HTTPStatusError("401 Unauthorized", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    with pytest.raises(ValueError, match="Twilio Error: Authenticate"):
        twilio_client.fetch_history()
