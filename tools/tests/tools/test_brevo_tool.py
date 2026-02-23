"""Tests for Brevo tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.brevo_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def get_tool_fn(mcp: FastMCP):
    """Factory fixture to get any tool function by name."""
    register_tools(mcp)

    def _get(name: str):
        return mcp._tool_manager._tools[name].fn

    return _get


# ============================================================================
# Credential Tests
# ============================================================================


class TestBrevoCredentials:
    """Tests for Brevo credential handling."""

    def test_no_credentials_returns_error(self, get_tool_fn, monkeypatch):
        """Send email without credentials returns helpful error."""
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        fn = get_tool_fn("brevo_send_email")

        result = fn(
            to_email="user@example.com",
            to_name="Test User",
            subject="Test",
            html_content="<p>Test</p>",
            from_email="sender@example.com",
            from_name="Sender",
        )

        assert "error" in result
        assert "Brevo credentials not configured" in result["error"]
        assert "help" in result

    def test_no_credentials_sms_returns_error(self, get_tool_fn, monkeypatch):
        """Send SMS without credentials returns helpful error."""
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        fn = get_tool_fn("brevo_send_sms")

        result = fn(to="+919876543210", content="Test SMS", sender="TestSender")

        assert "error" in result
        assert "Brevo credentials not configured" in result["error"]


# ============================================================================
# Send Email Tests
# ============================================================================


class TestBrevoSendEmail:
    """Tests for brevo_send_email tool."""

    def test_send_email_success(self, get_tool_fn, monkeypatch):
        """Successful email send returns message ID."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"messageId": "<abc123@smtp-relay.brevo.com>"}'
            mock_response.json.return_value = {
                "messageId": "<abc123@smtp-relay.brevo.com>"
            }
            mock_post.return_value = mock_response

            result = fn(
                to_email="user@example.com",
                to_name="John Doe",
                subject="Hello",
                html_content="<p>Hello!</p>",
                from_email="sender@example.com",
                from_name="Sender",
            )

        assert result["success"] is True
        assert result["message_id"] == "<abc123@smtp-relay.brevo.com>"

    def test_send_email_with_text_content(self, get_tool_fn, monkeypatch):
        """Email with text content includes it in request."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"messageId": "<abc123@smtp-relay.brevo.com>"}'
            mock_response.json.return_value = {
                "messageId": "<abc123@smtp-relay.brevo.com>"
            }
            mock_post.return_value = mock_response

            fn(
                to_email="user@example.com",
                to_name="John",
                subject="Hello",
                html_content="<p>Hello!</p>",
                from_email="sender@example.com",
                from_name="Sender",
                text_content="Hello!",
            )

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["textContent"] == "Hello!"

    def test_send_email_invalid_email(self, get_tool_fn, monkeypatch):
        """Invalid recipient email returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        result = fn(
            to_email="not-an-email",
            to_name="John",
            subject="Hello",
            html_content="<p>Hello!</p>",
            from_email="sender@example.com",
            from_name="Sender",
        )

        assert "error" in result
        assert "Invalid recipient email" in result["error"]

    def test_send_email_empty_subject(self, get_tool_fn, monkeypatch):
        """Empty subject returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        result = fn(
            to_email="user@example.com",
            to_name="John",
            subject="",
            html_content="<p>Hello!</p>",
            from_email="sender@example.com",
            from_name="Sender",
        )

        assert "error" in result
        assert "subject" in result["error"].lower()

    def test_send_email_empty_content(self, get_tool_fn, monkeypatch):
        """Empty HTML content returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        result = fn(
            to_email="user@example.com",
            to_name="John",
            subject="Hello",
            html_content="",
            from_email="sender@example.com",
            from_name="Sender",
        )

        assert "error" in result
        assert "content" in result["error"].lower()

    def test_send_email_invalid_auth(self, get_tool_fn, monkeypatch):
        """Invalid API key returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "invalid-key")
        fn = get_tool_fn("brevo_send_email")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.content = b'{"message": "Key not found"}'
            mock_response.json.return_value = {"message": "Key not found"}
            mock_post.return_value = mock_response

            result = fn(
                to_email="user@example.com",
                to_name="John",
                subject="Hello",
                html_content="<p>Hello!</p>",
                from_email="sender@example.com",
                from_name="Sender",
            )

        assert "error" in result
        assert "Invalid Brevo API key" in result["error"]

    def test_send_email_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_email")

        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            result = fn(
                to_email="user@example.com",
                to_name="John",
                subject="Hello",
                html_content="<p>Hello!</p>",
                from_email="sender@example.com",
                from_name="Sender",
            )

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Send SMS Tests
# ============================================================================


class TestBrevoSendSMS:
    """Tests for brevo_send_sms tool."""

    def test_send_sms_success(self, get_tool_fn, monkeypatch):
        """Successful SMS send returns reference."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_sms")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"reference": "ref123", "remainingCredits": 95.0}'
            mock_response.json.return_value = {
                "reference": "ref123",
                "remainingCredits": 95.0,
            }
            mock_post.return_value = mock_response

            result = fn(
                to="+919876543210",
                content="Your OTP is 1234",
                sender="HiveAgent",
            )

        assert result["success"] is True
        assert result["reference"] == "ref123"
        assert result["remaining_credits"] == 95.0

    def test_send_sms_invalid_phone_format(self, get_tool_fn, monkeypatch):
        """Phone number without + prefix returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_sms")

        result = fn(to="919876543210", content="Hello", sender="HiveAgent")

        assert "error" in result
        assert "international format" in result["error"]

    def test_send_sms_empty_content(self, get_tool_fn, monkeypatch):
        """Empty SMS content returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_sms")

        result = fn(to="+919876543210", content="", sender="HiveAgent")

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_send_sms_content_too_long(self, get_tool_fn, monkeypatch):
        """SMS content over 640 chars returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_sms")

        result = fn(to="+919876543210", content="x" * 641, sender="HiveAgent")

        assert "error" in result
        assert "too long" in result["error"].lower()

    def test_send_sms_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_send_sms")

        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            result = fn(to="+919876543210", content="Hello", sender="HiveAgent")

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Create Contact Tests
# ============================================================================


class TestBrevoCreateContact:
    """Tests for brevo_create_contact tool."""

    def test_create_contact_success(self, get_tool_fn, monkeypatch):
        """Successful contact creation returns ID."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_create_contact")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"id": 42}'
            mock_response.json.return_value = {"id": 42}
            mock_post.return_value = mock_response

            result = fn(
                email="user@example.com",
                first_name="John",
                last_name="Doe",
            )

        assert result["success"] is True
        assert result["id"] == 42
        assert result["email"] == "user@example.com"

    def test_create_contact_with_list_ids(self, get_tool_fn, monkeypatch):
        """Contact creation with list IDs parses correctly."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_create_contact")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"id": 43}'
            mock_response.json.return_value = {"id": 43}
            mock_post.return_value = mock_response

            fn(email="user@example.com", list_ids="2,5,8")

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["listIds"] == [2, 5, 8]

    def test_create_contact_invalid_email(self, get_tool_fn, monkeypatch):
        """Invalid email returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_create_contact")

        result = fn(email="not-an-email")

        assert "error" in result
        assert "Invalid email" in result["error"]

    def test_create_contact_invalid_list_ids(self, get_tool_fn, monkeypatch):
        """Non-integer list IDs return error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_create_contact")

        result = fn(email="user@example.com", list_ids="abc,def")

        assert "error" in result
        assert "list_ids" in result["error"].lower()

    def test_create_contact_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_create_contact")

        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            result = fn(email="user@example.com")

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Get Contact Tests
# ============================================================================


class TestBrevoGetContact:
    """Tests for brevo_get_contact tool."""

    def test_get_contact_success(self, get_tool_fn, monkeypatch):
        """Get contact returns full contact details."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_contact")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{}'
            mock_response.json.return_value = {
                "id": 42,
                "email": "user@example.com",
                "attributes": {
                    "FIRSTNAME": "John",
                    "LASTNAME": "Doe",
                    "SMS": "+919876543210",
                },
                "listIds": [2, 5],
                "emailBlacklisted": False,
                "smsBlacklisted": False,
                "createdAt": "2024-01-15T10:30:00Z",
                "modifiedAt": "2024-01-20T12:00:00Z",
            }
            mock_get.return_value = mock_response

            result = fn(email="user@example.com")

        assert result["success"] is True
        assert result["id"] == 42
        assert result["email"] == "user@example.com"
        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        assert result["list_ids"] == [2, 5]
        assert result["email_blacklisted"] is False

    def test_get_contact_not_found(self, get_tool_fn, monkeypatch):
        """Contact not found returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_contact")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.content = b'{"message": "Contact not found"}'
            mock_response.text = '{"message": "Contact not found"}'
            mock_get.return_value = mock_response

            result = fn(email="notfound@example.com")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_contact_invalid_email(self, get_tool_fn, monkeypatch):
        """Invalid email returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_contact")

        result = fn(email="not-valid")

        assert "error" in result
        assert "Invalid email" in result["error"]

    def test_get_contact_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_contact")

        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            result = fn(email="user@example.com")

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Update Contact Tests
# ============================================================================


class TestBrevoUpdateContact:
    """Tests for brevo_update_contact tool."""

    def test_update_contact_success(self, get_tool_fn, monkeypatch):
        """Successful update returns success."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_update_contact")

        with patch("httpx.put") as mock_put:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.content = b""
            mock_put.return_value = mock_response

            result = fn(
                email="user@example.com",
                first_name="Jane",
                last_name="Smith",
            )

        assert result["success"] is True
        assert result["email"] == "user@example.com"

    def test_update_contact_with_list_ids(self, get_tool_fn, monkeypatch):
        """Update with list IDs parses correctly."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_update_contact")

        with patch("httpx.put") as mock_put:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.content = b""
            mock_put.return_value = mock_response

            fn(email="user@example.com", list_ids="2,5,8")

        call_kwargs = mock_put.call_args[1]
        assert call_kwargs["json"]["listIds"] == [2, 5, 8]

    def test_update_contact_invalid_email(self, get_tool_fn, monkeypatch):
        """Invalid email returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_update_contact")

        result = fn(email="not-valid")

        assert "error" in result
        assert "Invalid email" in result["error"]

    def test_update_contact_invalid_list_ids(self, get_tool_fn, monkeypatch):
        """Non-integer list IDs return error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_update_contact")

        result = fn(email="user@example.com", list_ids="abc,def")

        assert "error" in result
        assert "list_ids" in result["error"].lower()

    def test_update_contact_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_update_contact")

        with patch("httpx.put", side_effect=httpx.TimeoutException("timeout")):
            result = fn(email="user@example.com", first_name="Jane")

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Get Email Stats Tests
# ============================================================================


class TestBrevoGetEmailStats:
    """Tests for brevo_get_email_stats tool."""

    def test_get_email_stats_success(self, get_tool_fn, monkeypatch):
        """Get email stats returns delivery details."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_email_stats")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{}'
            mock_response.json.return_value = {
                "messageId": "<abc123@smtp-relay.brevo.com>",
                "email": "user@example.com",
                "subject": "Hello",
                "date": "2024-01-15T10:30:00Z",
                "events": [
                    {"name": "delivered", "time": "2024-01-15T10:30:05Z"}
                ],
            }
            mock_get.return_value = mock_response

            result = fn(message_id="<abc123@smtp-relay.brevo.com>")

        assert result["success"] is True
        assert result["email"] == "user@example.com"
        assert result["subject"] == "Hello"
        assert len(result["events"]) == 1
        assert result["events"][0]["name"] == "delivered"

    def test_get_email_stats_empty_message_id(self, get_tool_fn, monkeypatch):
        """Empty message ID returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_email_stats")

        result = fn(message_id="")

        assert "error" in result
        assert "message_id" in result["error"].lower()

    def test_get_email_stats_not_found(self, get_tool_fn, monkeypatch):
        """Message ID not found returns error."""
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_email_stats")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.content = b'{"message": "Not found"}'
            mock_response.text = '{"message": "Not found"}'
            mock_get.return_value = mock_response

            result = fn(message_id="nonexistent")

        assert "error" in result

    def test_get_email_stats_timeout(self, get_tool_fn, monkeypatch):
        """Timeout returns error."""
        import httpx
        monkeypatch.setenv("BREVO_API_KEY", "test-api-key")
        fn = get_tool_fn("brevo_get_email_stats")

        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            result = fn(message_id="<abc123@smtp-relay.brevo.com>")

        assert "error" in result
        assert "timed out" in result["error"]


# ============================================================================
# Tool Registration Tests
# ============================================================================


class TestBrevoToolRegistration:
    """Tests for tool registration."""

    def test_all_tools_registered(self, mcp: FastMCP):
        """All 6 Brevo tools are registered."""
        register_tools(mcp)
        tools = list(mcp._tool_manager._tools.keys())

        expected_tools = [
            "brevo_send_email",
            "brevo_send_sms",
            "brevo_create_contact",
            "brevo_get_contact",
            "brevo_update_contact",
            "brevo_get_email_stats",
        ]
        for tool in expected_tools:
            assert tool in tools

    def test_tools_registered_with_credentials(self, mcp: FastMCP):
        """Tools register correctly when credentials adapter is provided."""
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.for_testing({"brevo": "test-key"})
        register_tools(mcp, credentials=creds)
        tools = list(mcp._tool_manager._tools.keys())

        assert "brevo_send_email" in tools
        assert "brevo_send_sms" in tools