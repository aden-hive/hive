"""Tests for email tool with multi-provider support (FastMCP)."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.email_tool import register_tools
from aden_tools.tools.email_tool.email_tool import _FOLDER_MAP

# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def send_email_fn(mcp: FastMCP):
    """Register and return the send_email tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["send_email"].fn


@pytest.fixture
def reply_email_fn(mcp: FastMCP):
    """Register and return the gmail_reply_email tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["gmail_reply_email"].fn


@pytest.fixture
def email_list_fn(mcp: FastMCP):
    """Register and return the email_list tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_list"].fn


@pytest.fixture
def email_read_fn(mcp: FastMCP):
    """Register and return the email_read tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_read"].fn


@pytest.fixture
def email_search_fn(mcp: FastMCP):
    """Register and return the email_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_search"].fn


@pytest.fixture
def email_labels_fn(mcp: FastMCP):
    """Register and return the email_labels tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_labels"].fn


# Helper to build a mock httpx response
def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


HTTPX_MODULE = "aden_tools.tools.email_tool.email_tool.httpx"


# ================================================================== #
# Existing send_email tests
# ================================================================== #


class TestSendEmail:
    """Tests for send_email tool."""

    def test_no_credentials_returns_error(self, send_email_fn, monkeypatch):
        """Send without credentials returns helpful error."""
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com", subject="Test", html="<p>Hi</p>", provider="gmail"
        )

        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]
        assert "help" in result

    def test_resend_explicit_missing_key(self, send_email_fn, monkeypatch):
        """Explicit resend provider without key returns error."""
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
        )

        assert "error" in result
        assert "Resend credentials not configured" in result["error"]
        assert "help" in result

    def test_missing_from_email_returns_error(self, send_email_fn, monkeypatch):
        """No from_email and no EMAIL_FROM env var returns error when using Resend."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)

        result = send_email_fn(
            to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
        )

        assert "error" in result
        assert "Sender email is required" in result["error"]
        assert "help" in result

    def test_from_email_falls_back_to_env_var(self, send_email_fn, monkeypatch):
        """EMAIL_FROM env var is used when from_email not provided."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "default@company.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_env"}
            result = send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
            )

        assert result["success"] is True
        call_args = mock_send.call_args[0][0]
        assert call_args["from"] == "default@company.com"

    def test_explicit_from_email_overrides_env_var(self, send_email_fn, monkeypatch):
        """Explicit from_email overrides EMAIL_FROM env var."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "default@company.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_override"}
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                from_email="custom@other.com",
                provider="resend",
            )

        assert result["success"] is True
        call_args = mock_send.call_args[0][0]
        assert call_args["from"] == "custom@other.com"

    def test_empty_recipient_returns_error(self, send_email_fn, monkeypatch):
        """Empty recipient returns error."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(to="", subject="Test", html="<p>Hi</p>", provider="resend")

        assert "error" in result

    def test_empty_subject_returns_error(self, send_email_fn, monkeypatch):
        """Empty subject returns error."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com", subject="", html="<p>Hi</p>", provider="resend"
        )

        assert "error" in result

    def test_subject_too_long_returns_error(self, send_email_fn, monkeypatch):
        """Subject over 998 chars returns error."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com", subject="x" * 999, html="<p>Hi</p>", provider="resend"
        )

        assert "error" in result

    def test_empty_html_returns_error(self, send_email_fn, monkeypatch):
        """Empty HTML body returns error."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(to="test@example.com", subject="Test", html="", provider="resend")

        assert "error" in result

    def test_to_string_normalized_to_list(self, send_email_fn, monkeypatch):
        """Single string 'to' is accepted and normalized."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_123"}
            result = send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
            )

        assert result["success"] is True
        mock_send.assert_called_once()

    def test_to_list_accepted(self, send_email_fn, monkeypatch):
        """List of recipients is accepted."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_456"}
            result = send_email_fn(
                to=["a@example.com", "b@example.com"],
                subject="Test",
                html="<p>Hi</p>",
                provider="resend",
            )

        assert result["success"] is True
        assert result["to"] == ["a@example.com", "b@example.com"]

    def test_cc_string_passed_to_provider(self, send_email_fn, monkeypatch):
        """Single CC string is passed to the provider."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_cc"}
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc="cc@example.com",
                provider="resend",
            )

        assert result["success"] is True
        call_args = mock_send.call_args[0][0]
        assert call_args["cc"] == ["cc@example.com"]

    def test_bcc_string_passed_to_provider(self, send_email_fn, monkeypatch):
        """Single BCC string is passed to the provider."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_bcc"}
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                bcc="bcc@example.com",
                provider="resend",
            )

        assert result["success"] is True
        call_args = mock_send.call_args[0][0]
        assert call_args["bcc"] == ["bcc@example.com"]

    def test_cc_and_bcc_lists_passed_to_provider(self, send_email_fn, monkeypatch):
        """CC and BCC lists are passed to the provider."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_cc_bcc"}
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc=["cc1@example.com", "cc2@example.com"],
                bcc=["bcc1@example.com"],
                provider="resend",
            )

        assert result["success"] is True
        call_args = mock_send.call_args[0][0]
        assert call_args["cc"] == ["cc1@example.com", "cc2@example.com"]
        assert call_args["bcc"] == ["bcc1@example.com"]

    def test_none_cc_bcc_not_included_in_payload(self, send_email_fn, monkeypatch):
        """None cc/bcc are not included in the API payload."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_no_cc"}
            send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
            )

        call_args = mock_send.call_args[0][0]
        assert "cc" not in call_args
        assert "bcc" not in call_args

    def test_empty_string_cc_not_included(self, send_email_fn, monkeypatch):
        """Empty string cc is treated as None and not included."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_empty_cc"}
            send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc="",
                bcc="",
                provider="resend",
            )

        call_args = mock_send.call_args[0][0]
        assert "cc" not in call_args
        assert "bcc" not in call_args

    def test_whitespace_cc_not_included(self, send_email_fn, monkeypatch):
        """Whitespace-only cc is treated as None."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_ws_cc"}
            send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", cc="   ", provider="resend"
            )

        call_args = mock_send.call_args[0][0]
        assert "cc" not in call_args

    def test_empty_list_cc_not_included(self, send_email_fn, monkeypatch):
        """Empty list cc is treated as None."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_empty_list"}
            send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc=[],
                bcc=[],
                provider="resend",
            )

        call_args = mock_send.call_args[0][0]
        assert "cc" not in call_args
        assert "bcc" not in call_args

    def test_list_with_empty_strings_filtered(self, send_email_fn, monkeypatch):
        """List containing empty strings filters them out."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_filtered"}
            send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc=["", "valid@example.com", "  "],
                provider="resend",
            )

        call_args = mock_send.call_args[0][0]
        assert call_args["cc"] == ["valid@example.com"]

    def test_list_of_only_empty_strings_not_included(self, send_email_fn, monkeypatch):
        """List of only empty/whitespace strings is treated as None."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_all_empty"}
            send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc=["", "  "],
                bcc=[""],
                provider="resend",
            )

        call_args = mock_send.call_args[0][0]
        assert "cc" not in call_args
        assert "bcc" not in call_args


class TestResendProvider:
    """Tests for Resend email provider."""

    def test_resend_success(self, send_email_fn, monkeypatch):
        """Successful send returns success dict with message ID."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "email_789"}
            result = send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
            )

        assert result["success"] is True
        assert result["provider"] == "resend"
        assert result["id"] == "email_789"

    def test_resend_api_error(self, send_email_fn, monkeypatch):
        """Resend API error returns error dict."""
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.side_effect = Exception("API rate limit exceeded")
            result = send_email_fn(
                to="test@example.com", subject="Test", html="<p>Hi</p>", provider="resend"
            )

        assert "error" in result


class TestGmailProvider:
    """Tests for Gmail email provider."""

    def test_gmail_success(self, send_email_fn, monkeypatch):
        """Successful Gmail send returns success dict with message ID."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_gmail_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "user@gmail.com")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "gmail_msg_123"}

        with patch(f"{HTTPX_MODULE}.post", return_value=mock_response) as mock_post:
            result = send_email_fn(
                to="recipient@example.com",
                subject="Test Gmail",
                html="<p>Hello from Gmail</p>",
                provider="gmail",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["id"] == "gmail_msg_123"
        assert result["to"] == ["recipient@example.com"]
        assert result["subject"] == "Test Gmail"

        # Verify Bearer token and Gmail API endpoint
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test_gmail_token"
        assert "gmail.googleapis.com" in call_kwargs[0][0]
        # Verify raw message is base64 encoded
        assert "raw" in call_kwargs[1]["json"]

    def test_gmail_missing_credentials(self, send_email_fn, monkeypatch):
        """Explicit Gmail provider without token returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com",
            subject="Test",
            html="<p>Hi</p>",
            provider="gmail",
        )

        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]
        assert "help" in result

    def test_gmail_api_error(self, send_email_fn, monkeypatch):
        """Gmail API non-200 response returns error dict."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_gmail_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "user@gmail.com")

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Insufficient permissions"

        with patch(f"{HTTPX_MODULE}.post", return_value=mock_response):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="gmail",
            )

        assert "error" in result
        assert "403" in result["error"]

    def test_gmail_token_expired(self, send_email_fn, monkeypatch):
        """Gmail 401 response returns token expiry error with help."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "expired_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "user@gmail.com")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid credentials"

        with patch(f"{HTTPX_MODULE}.post", return_value=mock_response):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="gmail",
            )

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
        assert "help" in result

    def test_auto_prefers_gmail_over_resend(self, send_email_fn, monkeypatch):
        """Auto mode uses Gmail when both Gmail and Resend are available."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_gmail_token")
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "user@gmail.com")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "gmail_auto_123"}

        with (
            patch(f"{HTTPX_MODULE}.post", return_value=mock_response),
            patch("resend.Emails.send") as mock_resend,
        ):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"
        mock_resend.assert_not_called()

    def test_auto_falls_back_to_resend(self, send_email_fn, monkeypatch):
        """Auto mode falls back to Resend when Gmail is not available."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "resend_fallback"}
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
            )

        assert result["success"] is True
        assert result["provider"] == "resend"

    def test_gmail_no_from_email_ok(self, send_email_fn, monkeypatch):
        """Gmail works without from_email (defaults to authenticated user)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_gmail_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "gmail_no_from"}

        with patch(f"{HTTPX_MODULE}.post", return_value=mock_response):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="gmail",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"


# ================================================================== #
# Outlook send provider tests
# ================================================================== #


class TestOutlookSendProvider:
    """Tests for Outlook send via Microsoft Graph API."""

    def test_outlook_send_success(self, send_email_fn, monkeypatch):
        """Successful Outlook send returns success dict."""
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "user@outlook.com")

        with patch(f"{HTTPX_MODULE}.post", return_value=_mock_response(202)):
            result = send_email_fn(
                to="recipient@example.com",
                subject="Test Outlook",
                html="<p>Hello from Outlook</p>",
                provider="outlook",
            )

        assert result["success"] is True
        assert result["provider"] == "outlook"
        assert result["id"] == ""  # Graph sendMail returns 202 with no body
        assert result["to"] == ["recipient@example.com"]

    def test_outlook_send_request_format(self, send_email_fn, monkeypatch):
        """Outlook send sends correctly formatted Graph API request."""
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)

        with patch(f"{HTTPX_MODULE}.post", return_value=_mock_response(202)) as mock_post:
            send_email_fn(
                to=["a@example.com", "b@example.com"],
                subject="Test",
                html="<p>Hi</p>",
                cc="cc@example.com",
                provider="outlook",
            )

        call_kwargs = mock_post.call_args
        assert "graph.microsoft.com" in call_kwargs[0][0]
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test_outlook_token"
        msg = call_kwargs[1]["json"]["message"]
        assert msg["subject"] == "Test"
        assert len(msg["toRecipients"]) == 2
        assert len(msg["ccRecipients"]) == 1

    def test_outlook_send_missing_credentials(self, send_email_fn, monkeypatch):
        """Explicit Outlook provider without token returns error."""
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        result = send_email_fn(
            to="test@example.com",
            subject="Test",
            html="<p>Hi</p>",
            provider="outlook",
        )

        assert "error" in result
        assert "Outlook credentials not configured" in result["error"]

    def test_outlook_send_token_expired(self, send_email_fn, monkeypatch):
        """Outlook 401 response returns token expiry error."""
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "expired_token")
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)

        with patch(f"{HTTPX_MODULE}.post", return_value=_mock_response(401, text="Unauthorized")):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="outlook",
            )

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()

    def test_auto_send_falls_back_to_outlook(self, send_email_fn, monkeypatch):
        """Auto mode falls back to Outlook when Gmail is not available."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)

        with patch(f"{HTTPX_MODULE}.post", return_value=_mock_response(202)):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
            )

        assert result["success"] is True
        assert result["provider"] == "outlook"


# ================================================================== #
# Folder mapping tests
# ================================================================== #


class TestFolderMapping:
    """Tests for folder name normalization."""

    def test_inbox_gmail(self):
        assert _FOLDER_MAP["INBOX"][0] == "INBOX"

    def test_inbox_outlook(self):
        assert _FOLDER_MAP["INBOX"][1] == "inbox"

    def test_sent_gmail(self):
        assert _FOLDER_MAP["SENT"][0] == "SENT"

    def test_sent_outlook(self):
        assert _FOLDER_MAP["SENT"][1] == "sentItems"

    def test_drafts_gmail(self):
        assert _FOLDER_MAP["DRAFTS"][0] == "DRAFT"

    def test_drafts_outlook(self):
        assert _FOLDER_MAP["DRAFTS"][1] == "drafts"

    def test_trash_gmail(self):
        assert _FOLDER_MAP["TRASH"][0] == "TRASH"

    def test_trash_outlook(self):
        assert _FOLDER_MAP["TRASH"][1] == "deletedItems"

    def test_spam_gmail(self):
        assert _FOLDER_MAP["SPAM"][0] == "SPAM"

    def test_spam_outlook(self):
        assert _FOLDER_MAP["SPAM"][1] == "junkemail"

    def test_all_canonical_names_present(self):
        expected = {"INBOX", "SENT", "DRAFTS", "TRASH", "SPAM"}
        assert set(_FOLDER_MAP.keys()) == expected


# ================================================================== #
# email_list tests
# ================================================================== #


class TestEmailList:
    """Tests for email_list tool."""

    def test_no_credentials_returns_error(self, email_list_fn, monkeypatch):
        """List without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_list_fn()
        assert "error" in result
        assert "No email read credentials" in result["error"]

    def test_gmail_list_success(self, email_list_fn, monkeypatch):
        """Gmail list returns messages."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(
            200,
            {
                "messages": [{"id": "msg1"}, {"id": "msg2"}],
                "resultSizeEstimate": 2,
            },
        )
        detail_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "snippet": "Hello...",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Test Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ]
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", side_effect=[list_resp, detail_resp, detail_resp]):
            result = email_list_fn(folder="INBOX", max_results=10)

        assert result["provider"] == "gmail"
        assert len(result["messages"]) == 2
        assert result["total"] == 2

    def test_max_results_capped(self, email_list_fn, monkeypatch):
        """max_results is capped at 500."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(200, {"messages": [], "resultSizeEstimate": 0})

        with patch(f"{HTTPX_MODULE}.get", return_value=list_resp) as mock_get:
            email_list_fn(max_results=1000)

        call_params = mock_get.call_args[1]["params"]
        assert call_params["maxResults"] == 500

    def test_unread_only_filter(self, email_list_fn, monkeypatch):
        """unread_only adds query param for Gmail."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(200, {"messages": [], "resultSizeEstimate": 0})

        with patch(f"{HTTPX_MODULE}.get", return_value=list_resp) as mock_get:
            email_list_fn(unread_only=True)

        call_params = mock_get.call_args[1]["params"]
        assert call_params["q"] == "is:unread"


# ================================================================== #
# email_read tests
# ================================================================== #


class TestEmailRead:
    """Tests for email_read tool."""

    def test_no_credentials_returns_error(self, email_read_fn, monkeypatch):
        """Read without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_read_fn(message_id="msg1")
        assert "error" in result

    def test_gmail_read_success(self, email_read_fn, monkeypatch):
        """Gmail read returns full message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        body_data = base64.urlsafe_b64encode(b"<p>Hello World</p>").decode()
        resp = _mock_response(
            200,
            {
                "id": "msg123",
                "snippet": "Hello...",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "Subject", "value": "Test Email"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ],
                    "body": {"data": body_data},
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_read_fn(message_id="msg123", provider="gmail")

        assert result["provider"] == "gmail"
        assert result["id"] == "msg123"
        assert result["subject"] == "Test Email"
        assert result["from"] == "sender@example.com"
        assert "Hello World" in result["body_html"]

    def test_gmail_read_404(self, email_read_fn, monkeypatch):
        """Gmail read 404 returns not found error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        with patch(f"{HTTPX_MODULE}.get", return_value=_mock_response(404)):
            result = email_read_fn(message_id="nonexistent", provider="gmail")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_gmail_read_multipart(self, email_read_fn, monkeypatch):
        """Gmail read parses multipart MIME messages."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        text_data = base64.urlsafe_b64encode(b"Plain text body").decode()
        html_data = base64.urlsafe_b64encode(b"<p>HTML body</p>").decode()
        resp = _mock_response(
            200,
            {
                "id": "msg_multi",
                "snippet": "Plain text...",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "Subject", "value": "Multipart"},
                        {"name": "From", "value": "sender@example.com"},
                    ],
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": text_data}},
                        {"mimeType": "text/html", "body": {"data": html_data}},
                        {
                            "mimeType": "application/pdf",
                            "filename": "doc.pdf",
                            "body": {"size": 1024},
                        },
                    ],
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_read_fn(message_id="msg_multi", provider="gmail")

        assert result["body_text"] == "Plain text body"
        assert "<p>HTML body</p>" in result["body_html"]
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["name"] == "doc.pdf"


# ================================================================== #
# email_search tests
# ================================================================== #


class TestEmailSearch:
    """Tests for email_search tool."""

    def test_empty_query_returns_error(self, email_search_fn, monkeypatch):
        """Empty query returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_search_fn(query="")
        assert "error" in result
        assert "query is required" in result["error"].lower()

    def test_whitespace_query_returns_error(self, email_search_fn, monkeypatch):
        """Whitespace-only query returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_search_fn(query="   ")
        assert "error" in result

    def test_gmail_search_success(self, email_search_fn, monkeypatch):
        """Gmail search returns matching messages."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(
            200,
            {
                "messages": [{"id": "search1"}],
                "resultSizeEstimate": 1,
            },
        )
        detail_resp = _mock_response(
            200,
            {
                "id": "search1",
                "snippet": "Found it",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Search Result"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ]
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", side_effect=[list_resp, detail_resp]) as mock_get:
            result = email_search_fn(query="from:sender@example.com", max_results=5)

        assert result["provider"] == "gmail"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["subject"] == "Search Result"
        # Verify query was passed
        first_call_params = mock_get.call_args_list[0][1]["params"]
        assert first_call_params["q"] == "from:sender@example.com"

    def test_no_credentials_returns_error(self, email_search_fn, monkeypatch):
        """Search without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_search_fn(query="test")
        assert "error" in result


# ================================================================== #
# email_labels tests
# ================================================================== #


class TestEmailLabels:
    """Tests for email_labels tool."""

    def test_no_credentials_returns_error(self, email_labels_fn, monkeypatch):
        """Labels without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_labels_fn()
        assert "error" in result

    def test_gmail_labels_success(self, email_labels_fn, monkeypatch):
        """Gmail labels returns system and user labels."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(
            200,
            {
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {"id": "SENT", "name": "SENT", "type": "system"},
                    {"id": "Label_1", "name": "My Label", "type": "user"},
                ],
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_labels_fn(provider="gmail")

        assert result["provider"] == "gmail"
        assert len(result["labels"]) == 3
        system_labels = [lb for lb in result["labels"] if lb["type"] == "system"]
        user_labels = [lb for lb in result["labels"] if lb["type"] == "user"]
        assert len(system_labels) == 2
        assert len(user_labels) == 1


# ================================================================== #
# Gmail provider-specific tests
# ================================================================== #


class TestGmailListProvider:
    """Tests for Gmail API request format in list operations."""

    def test_gmail_list_request_format(self, email_list_fn, monkeypatch):
        """Gmail list sends correct API request."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(200, {"messages": [], "resultSizeEstimate": 0})

        with patch(f"{HTTPX_MODULE}.get", return_value=list_resp) as mock_get:
            email_list_fn(folder="SENT", max_results=5)

        call_args = mock_get.call_args
        assert "gmail.googleapis.com" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test_token"
        assert call_args[1]["params"]["labelIds"] == "SENT"
        assert call_args[1]["params"]["maxResults"] == 5

    def test_gmail_list_response_parsing(self, email_list_fn, monkeypatch):
        """Gmail list correctly parses message metadata."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        list_resp = _mock_response(
            200,
            {
                "messages": [{"id": "m1"}],
                "resultSizeEstimate": 1,
            },
        )
        detail_resp = _mock_response(
            200,
            {
                "id": "m1",
                "snippet": "Preview text",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Unread Email"},
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "Date", "value": "Tue, 2 Jan 2024 09:00:00 +0000"},
                    ]
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", side_effect=[list_resp, detail_resp]):
            result = email_list_fn()

        msg = result["messages"][0]
        assert msg["id"] == "m1"
        assert msg["subject"] == "Unread Email"
        assert msg["from"] == "alice@example.com"
        assert msg["is_read"] is False  # UNREAD label present


class TestGmailReadProvider:
    """Tests for Gmail MIME payload parsing."""

    def test_headers_extraction(self, email_read_fn, monkeypatch):
        """Gmail read extracts all relevant headers."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        body_data = base64.urlsafe_b64encode(b"Body").decode()
        resp = _mock_response(
            200,
            {
                "id": "hdr_msg",
                "snippet": "Body",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": "Subject Line"},
                        {"name": "From", "value": "from@example.com"},
                        {"name": "To", "value": "to@example.com"},
                        {"name": "Cc", "value": "cc@example.com"},
                        {"name": "Date", "value": "Wed, 3 Jan 2024 10:00:00 +0000"},
                    ],
                    "body": {"data": body_data},
                },
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_read_fn(message_id="hdr_msg", provider="gmail")

        assert result["subject"] == "Subject Line"
        assert result["from"] == "from@example.com"
        assert result["to"] == "to@example.com"
        assert result["cc"] == "cc@example.com"
        assert result["date"] == "Wed, 3 Jan 2024 10:00:00 +0000"


# ================================================================== #
# Outlook provider-specific tests
# ================================================================== #


class TestOutlookListProvider:
    """Tests for Outlook Graph API request format in list operations."""

    def test_outlook_list_request_format(self, email_list_fn, monkeypatch):
        """Outlook list sends correct Graph API request."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        resp = _mock_response(200, {"value": []})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            email_list_fn(folder="INBOX", max_results=5, provider="outlook")

        call_args = mock_get.call_args
        assert "graph.microsoft.com" in call_args[0][0]
        assert "/mailFolders/inbox/messages" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test_outlook_token"
        assert call_args[1]["params"]["$top"] == 5

    def test_outlook_list_response_parsing(self, email_list_fn, monkeypatch):
        """Outlook list correctly parses message objects."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        resp = _mock_response(
            200,
            {
                "value": [
                    {
                        "id": "out_m1",
                        "subject": "Outlook Email",
                        "from": {"emailAddress": {"address": "sender@outlook.com"}},
                        "receivedDateTime": "2024-01-01T12:00:00Z",
                        "bodyPreview": "Preview...",
                        "isRead": True,
                    },
                ]
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_list_fn(provider="outlook")

        assert result["provider"] == "outlook"
        msg = result["messages"][0]
        assert msg["id"] == "out_m1"
        assert msg["subject"] == "Outlook Email"
        assert msg["from"] == "sender@outlook.com"
        assert msg["is_read"] is True

    def test_outlook_list_unread_filter(self, email_list_fn, monkeypatch):
        """Outlook list adds $filter for unread_only."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        resp = _mock_response(200, {"value": []})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            email_list_fn(unread_only=True, provider="outlook")

        call_params = mock_get.call_args[1]["params"]
        assert call_params["$filter"] == "isRead eq false"


class TestOutlookReadProvider:
    """Tests for Outlook Graph message object parsing."""

    def test_outlook_read_success(self, email_read_fn, monkeypatch):
        """Outlook read returns full message details."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        resp = _mock_response(
            200,
            {
                "id": "out_full",
                "subject": "Full Outlook Message",
                "from": {"emailAddress": {"address": "from@outlook.com"}},
                "toRecipients": [{"emailAddress": {"address": "to@outlook.com"}}],
                "ccRecipients": [{"emailAddress": {"address": "cc@outlook.com"}}],
                "receivedDateTime": "2024-01-01T12:00:00Z",
                "bodyPreview": "Preview...",
                "isRead": False,
                "body": {"contentType": "html", "content": "<p>Full body</p>"},
                "attachments": [
                    {
                        "name": "report.xlsx",
                        "size": 2048,
                        "contentType": "application/vnd.openxmlformats",
                    },
                ],
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_read_fn(message_id="out_full", provider="outlook")

        assert result["provider"] == "outlook"
        assert result["subject"] == "Full Outlook Message"
        assert result["from"] == "from@outlook.com"
        assert result["to"] == "to@outlook.com"
        assert result["cc"] == "cc@outlook.com"
        assert "<p>Full body</p>" in result["body_html"]
        assert result["body_text"] == ""  # contentType is html
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["name"] == "report.xlsx"

    def test_outlook_read_404(self, email_read_fn, monkeypatch):
        """Outlook read 404 returns not found error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        with patch(f"{HTTPX_MODULE}.get", return_value=_mock_response(404)):
            result = email_read_fn(message_id="nonexistent", provider="outlook")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_outlook_read_text_body(self, email_read_fn, monkeypatch):
        """Outlook read correctly handles text content type."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_outlook_token")

        resp = _mock_response(
            200,
            {
                "id": "out_text",
                "subject": "Plain Text",
                "from": {"emailAddress": {"address": "from@outlook.com"}},
                "toRecipients": [],
                "ccRecipients": [],
                "receivedDateTime": "2024-01-01T12:00:00Z",
                "bodyPreview": "Plain...",
                "isRead": True,
                "body": {"contentType": "text", "content": "Plain text content"},
                "attachments": [],
            },
        )

        with patch(f"{HTTPX_MODULE}.get", return_value=resp):
            result = email_read_fn(message_id="out_text", provider="outlook")

        assert result["body_text"] == "Plain text content"
        assert result["body_html"] == ""


# ================================================================== #
# Auto-detection for read operations
# ================================================================== #


class TestReadAutoProvider:
    """Tests for auto provider detection in read operations."""

    def test_auto_prefers_gmail(self, email_list_fn, monkeypatch):
        """Auto mode prefers Gmail when both are available."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "gmail_token")
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "outlook_token")

        resp = _mock_response(200, {"messages": [], "resultSizeEstimate": 0})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            result = email_list_fn()

        assert result["provider"] == "gmail"
        # Verify it called Gmail API, not Outlook
        assert "gmail.googleapis.com" in mock_get.call_args[0][0]

    def test_auto_falls_back_to_outlook(self, email_list_fn, monkeypatch):
        """Auto mode falls back to Outlook when Gmail is unavailable."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "outlook_token")

        resp = _mock_response(200, {"value": []})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            result = email_list_fn()

        assert result["provider"] == "outlook"
        assert "graph.microsoft.com" in mock_get.call_args[0][0]

    def test_explicit_gmail_uses_gmail(self, email_labels_fn, monkeypatch):
        """Explicit gmail provider uses Gmail even if Outlook is available."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "gmail_token")
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "outlook_token")

        resp = _mock_response(200, {"labels": []})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            result = email_labels_fn(provider="gmail")

        assert result["provider"] == "gmail"
        assert "gmail.googleapis.com" in mock_get.call_args[0][0]

    def test_explicit_outlook_uses_outlook(self, email_labels_fn, monkeypatch):
        """Explicit outlook provider uses Outlook even if Gmail is available."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "gmail_token")
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "outlook_token")

        resp = _mock_response(200, {"value": []})

        with patch(f"{HTTPX_MODULE}.get", return_value=resp) as mock_get:
            result = email_labels_fn(provider="outlook")

        assert result["provider"] == "outlook"
        assert "graph.microsoft.com" in mock_get.call_args[0][0]

    def test_explicit_gmail_missing_returns_error(self, email_search_fn, monkeypatch):
        """Explicit gmail provider without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "outlook_token")

        result = email_search_fn(query="test", provider="gmail")
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]

    def test_explicit_outlook_missing_returns_error(self, email_read_fn, monkeypatch):
        """Explicit outlook provider without credentials returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "gmail_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_read_fn(message_id="test", provider="outlook")
        assert "error" in result
        assert "Outlook credentials not configured" in result["error"]


# ================================================================== #
# email_mark_read tests
# ================================================================== #


@pytest.fixture
def email_mark_read_fn(mcp: FastMCP):
    """Register and return the email_mark_read tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_mark_read"].fn


class TestEmailMarkRead:
    """Tests for email_mark_read tool."""

    def test_no_credentials_returns_error(self, email_mark_read_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_mark_read_fn(message_id="msg1")
        assert "error" in result

    def test_gmail_mark_as_read(self, email_mark_read_fn, monkeypatch):
        """Gmail mark as read removes UNREAD label."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(200, {"id": "msg1", "labelIds": ["INBOX"]})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_mark_read_fn(message_id="msg1", read=True)

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["is_read"] is True
        call_json = mock_post.call_args[1]["json"]
        assert call_json == {"removeLabelIds": ["UNREAD"]}

    def test_gmail_mark_as_unread(self, email_mark_read_fn, monkeypatch):
        """Gmail mark as unread adds UNREAD label."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(200, {"id": "msg1", "labelIds": ["INBOX", "UNREAD"]})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_mark_read_fn(message_id="msg1", read=False)

        assert result["success"] is True
        assert result["is_read"] is False
        call_json = mock_post.call_args[1]["json"]
        assert call_json == {"addLabelIds": ["UNREAD"]}

    def test_outlook_mark_as_read(self, email_mark_read_fn, monkeypatch):
        """Outlook mark as read patches isRead=true."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(200, {"id": "msg1", "isRead": True})

        with patch(f"{HTTPX_MODULE}.patch", return_value=resp) as mock_patch:
            result = email_mark_read_fn(message_id="msg1", read=True)

        assert result["success"] is True
        assert result["provider"] == "outlook"
        call_json = mock_patch.call_args[1]["json"]
        assert call_json == {"isRead": True}


# ================================================================== #
# email_delete tests
# ================================================================== #


@pytest.fixture
def email_delete_fn(mcp: FastMCP):
    """Register and return the email_delete tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_delete"].fn


class TestEmailDelete:
    """Tests for email_delete tool."""

    def test_no_credentials_returns_error(self, email_delete_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_delete_fn(message_id="msg1")
        assert "error" in result

    def test_gmail_trash(self, email_delete_fn, monkeypatch):
        """Gmail trash sends POST to /trash endpoint."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(200, {"id": "msg1", "labelIds": ["TRASH"]})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_delete_fn(message_id="msg1", permanent=False)

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["permanent"] is False
        assert "/trash" in mock_post.call_args[0][0]

    def test_gmail_permanent_delete(self, email_delete_fn, monkeypatch):
        """Gmail permanent delete sends DELETE request."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(204)

        with patch(f"{HTTPX_MODULE}.delete", return_value=resp) as mock_del:
            result = email_delete_fn(message_id="msg1", permanent=True)

        assert result["success"] is True
        assert result["permanent"] is True
        assert "messages/msg1" in mock_del.call_args[0][0]

    def test_outlook_trash(self, email_delete_fn, monkeypatch):
        """Outlook trash moves to deletedItems."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(200, {"id": "msg1_moved"})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_delete_fn(message_id="msg1", permanent=False)

        assert result["success"] is True
        assert result["provider"] == "outlook"
        call_json = mock_post.call_args[1]["json"]
        assert call_json["destinationId"] == "deletedItems"

    def test_outlook_permanent_delete(self, email_delete_fn, monkeypatch):
        """Outlook permanent delete sends DELETE request."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(204)

        with patch(f"{HTTPX_MODULE}.delete", return_value=resp):
            result = email_delete_fn(message_id="msg1", permanent=True)

        assert result["success"] is True
        assert result["permanent"] is True


# ================================================================== #
# email_reply tests
# ================================================================== #


@pytest.fixture
def email_reply_fn(mcp: FastMCP):
    """Register and return the email_reply tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_reply"].fn


class TestEmailReply:
    """Tests for email_reply tool."""

    def test_no_credentials_returns_error(self, email_reply_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_reply_fn(message_id="msg1", body="<p>Reply</p>")
        assert "error" in result

    def test_empty_body_returns_error(self, email_reply_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_reply_fn(message_id="msg1", body="")
        assert "error" in result
        assert "body is required" in result["error"].lower()

    def test_gmail_reply_single(self, email_reply_fn, monkeypatch):
        """Gmail reply sends MIME with In-Reply-To and threadId."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        # Single metadata fetch via _fetch_original_message
        meta_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "threadId": "thread1",
                "payload": {
                    "headers": [
                        {"name": "Message-ID", "value": "<abc@mail.gmail.com>"},
                        {"name": "Subject", "value": "Original Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Cc", "value": ""},
                    ]
                },
            },
        )
        # Send call
        send_resp = _mock_response(200, {"id": "reply_msg1"})

        with (
            patch(f"{HTTPX_MODULE}.get", return_value=meta_resp),
            patch(f"{HTTPX_MODULE}.post", return_value=send_resp) as mock_post,
        ):
            result = email_reply_fn(message_id="msg1", body="<p>My reply</p>")

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["thread_id"] == "thread1"
        assert result["reply_all"] is False
        # Verify threadId sent in body
        call_json = mock_post.call_args[1]["json"]
        assert call_json["threadId"] == "thread1"

    def test_gmail_reply_all(self, email_reply_fn, monkeypatch):
        """Gmail reply all includes original To/Cc as recipients."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        # Single metadata fetch via _fetch_original_message
        meta_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "threadId": "thread1",
                "payload": {
                    "headers": [
                        {"name": "Message-ID", "value": "<abc@mail.gmail.com>"},
                        {"name": "Subject", "value": "Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com, other@example.com"},
                        {"name": "Cc", "value": "cc@example.com"},
                    ]
                },
            },
        )
        send_resp = _mock_response(200, {"id": "reply_all_msg"})

        with (
            patch(f"{HTTPX_MODULE}.get", return_value=meta_resp),
            patch(f"{HTTPX_MODULE}.post", return_value=send_resp),
        ):
            result = email_reply_fn(message_id="msg1", body="<p>Reply all</p>", reply_all=True)

        assert result["success"] is True
        assert result["reply_all"] is True

    def test_outlook_reply(self, email_reply_fn, monkeypatch):
        """Outlook reply sends POST to /reply endpoint."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(202)

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_reply_fn(message_id="msg1", body="<p>Reply</p>")

        assert result["success"] is True
        assert result["provider"] == "outlook"
        assert "/reply" in mock_post.call_args[0][0]
        assert "replyAll" not in mock_post.call_args[0][0]

    def test_outlook_reply_all(self, email_reply_fn, monkeypatch):
        """Outlook reply all sends POST to /replyAll endpoint."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(202)

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_reply_fn(message_id="msg1", body="<p>Reply all</p>", reply_all=True)

        assert result["success"] is True
        assert result["reply_all"] is True
        assert "/replyAll" in mock_post.call_args[0][0]


# ================================================================== #
# email_forward tests
# ================================================================== #


@pytest.fixture
def email_forward_fn(mcp: FastMCP):
    """Register and return the email_forward tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_forward"].fn


class TestEmailForward:
    """Tests for email_forward tool."""

    def test_no_credentials_returns_error(self, email_forward_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_forward_fn(message_id="msg1", to="fwd@example.com")
        assert "error" in result

    def test_empty_to_returns_error(self, email_forward_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_forward_fn(message_id="msg1", to="")
        assert "error" in result
        assert "Recipient" in result["error"]

    def test_gmail_forward(self, email_forward_fn, monkeypatch):
        """Gmail forward fetches original and sends with Fwd: prefix."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        body_data = base64.urlsafe_b64encode(b"<p>Original content</p>").decode()
        read_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "snippet": "Original",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "Subject", "value": "Original Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ],
                    "body": {"data": body_data},
                },
            },
        )
        send_resp = _mock_response(200, {"id": "fwd_msg1"})

        with (
            patch(f"{HTTPX_MODULE}.get", return_value=read_resp),
            patch(f"{HTTPX_MODULE}.post", return_value=send_resp),
        ):
            result = email_forward_fn(
                message_id="msg1",
                to="fwd@example.com",
                body="<p>FYI</p>",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["forwarded_to"] == "fwd@example.com"

    def test_gmail_forward_without_body(self, email_forward_fn, monkeypatch):
        """Gmail forward works without an additional body message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        body_data = base64.urlsafe_b64encode(b"<p>Content</p>").decode()
        read_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "snippet": "Content",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "Subject", "value": "Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024"},
                    ],
                    "body": {"data": body_data},
                },
            },
        )
        send_resp = _mock_response(200, {"id": "fwd_msg2"})

        with (
            patch(f"{HTTPX_MODULE}.get", return_value=read_resp),
            patch(f"{HTTPX_MODULE}.post", return_value=send_resp),
        ):
            result = email_forward_fn(message_id="msg1", to="fwd@example.com")

        assert result["success"] is True

    def test_outlook_forward(self, email_forward_fn, monkeypatch):
        """Outlook forward sends POST to /forward endpoint."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(202)

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_forward_fn(
                message_id="msg1",
                to="fwd@example.com",
                body="FYI",
            )

        assert result["success"] is True
        assert result["provider"] == "outlook"
        assert result["forwarded_to"] == "fwd@example.com"
        assert "/forward" in mock_post.call_args[0][0]
        call_json = mock_post.call_args[1]["json"]
        assert call_json["toRecipients"][0]["emailAddress"]["address"] == "fwd@example.com"


# ================================================================== #
# email_move tests
# ================================================================== #


@pytest.fixture
def email_move_fn(mcp: FastMCP):
    """Register and return the email_move tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_move"].fn


class TestEmailMove:
    """Tests for email_move tool."""

    def test_no_credentials_returns_error(self, email_move_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_move_fn(message_id="msg1", destination="TRASH")
        assert "error" in result

    def test_empty_destination_returns_error(self, email_move_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_move_fn(message_id="msg1", destination="")
        assert "error" in result
        assert "Destination" in result["error"]

    def test_gmail_move_to_trash(self, email_move_fn, monkeypatch):
        """Gmail move modifies labels (adds TRASH, removes INBOX)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(200, {"id": "msg1", "labelIds": ["TRASH"]})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_move_fn(message_id="msg1", destination="TRASH")

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["destination"] == "TRASH"
        call_json = mock_post.call_args[1]["json"]
        assert "TRASH" in call_json["addLabelIds"]
        assert "INBOX" in call_json["removeLabelIds"]

    def test_outlook_move_to_trash(self, email_move_fn, monkeypatch):
        """Outlook move sends POST to /move with deletedItems."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(200, {"id": "msg1_moved"})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_move_fn(message_id="msg1", destination="TRASH")

        assert result["success"] is True
        assert result["provider"] == "outlook"
        call_json = mock_post.call_args[1]["json"]
        assert call_json["destinationId"] == "deletedItems"

    def test_gmail_move_api_error(self, email_move_fn, monkeypatch):
        """Gmail move returns error on API failure."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(400, text="Invalid label")

        with patch(f"{HTTPX_MODULE}.post", return_value=resp):
            result = email_move_fn(message_id="msg1", destination="NONEXISTENT_LABEL")

        assert "error" in result


# ================================================================== #
# email_bulk_delete tests
# ================================================================== #


@pytest.fixture
def email_bulk_delete_fn(mcp: FastMCP):
    """Register and return the email_bulk_delete tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["email_bulk_delete"].fn


class TestEmailBulkDelete:
    """Tests for email_bulk_delete tool."""

    def test_empty_list_returns_success(self, email_bulk_delete_fn, monkeypatch):
        """Empty message_ids list returns immediate success."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = email_bulk_delete_fn(message_ids=[])
        assert result["success"] is True
        assert result["deleted_count"] == 0

    def test_no_credentials_returns_error(self, email_bulk_delete_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        result = email_bulk_delete_fn(message_ids=["msg1", "msg2"])
        assert "error" in result

    def test_gmail_bulk_trash(self, email_bulk_delete_fn, monkeypatch):
        """Gmail bulk trash calls individual trash for each message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(200, {"id": "msg1", "labelIds": ["TRASH"]})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_bulk_delete_fn(
                message_ids=["msg1", "msg2", "msg3"],
                permanent=False,
            )

        assert result["success"] is True
        assert result["deleted_count"] == 3
        assert result["permanent"] is False
        assert mock_post.call_count == 3

    def test_gmail_bulk_permanent_uses_batch_delete(self, email_bulk_delete_fn, monkeypatch):
        """Gmail permanent bulk delete uses batchDelete API."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        monkeypatch.delenv("MICROSOFT_GRAPH_ACCESS_TOKEN", raising=False)

        resp = _mock_response(204)

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_bulk_delete_fn(
                message_ids=["msg1", "msg2"],
                permanent=True,
            )

        assert result["success"] is True
        assert result["permanent"] is True
        assert result["deleted_count"] == 2
        # Should be a single batchDelete call
        mock_post.assert_called_once()
        assert "/batchDelete" in mock_post.call_args[0][0]
        call_json = mock_post.call_args[1]["json"]
        assert call_json["ids"] == ["msg1", "msg2"]

    def test_outlook_bulk_trash(self, email_bulk_delete_fn, monkeypatch):
        """Outlook bulk trash loops individual move calls."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "test_token")

        resp = _mock_response(200, {"id": "moved"})

        with patch(f"{HTTPX_MODULE}.post", return_value=resp) as mock_post:
            result = email_bulk_delete_fn(
                message_ids=["msg1", "msg2"],
                permanent=False,
            )

        assert result["success"] is True
        assert result["provider"] == "outlook"
        assert result["deleted_count"] == 2
        assert mock_post.call_count == 2


# ================================================================== #
# Gmail reply tests (gmail_reply_email tool)
# ================================================================== #

_HTTPX_GET = f"{HTTPX_MODULE}.get"
_HTTPX_POST = f"{HTTPX_MODULE}.post"


def _mock_original_message_response():
    """Helper: mock response for fetching the original message."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "id": "orig_123",
        "threadId": "thread_abc",
        "payload": {
            "headers": [
                {"name": "Message-ID", "value": "<orig@mail.gmail.com>"},
                {"name": "Subject", "value": "Hello there"},
                {"name": "From", "value": "sender@example.com"},
            ]
        },
    }
    return resp


class TestGmailReplyEmail:
    """Tests for gmail_reply_email tool."""

    def test_missing_credentials(self, reply_email_fn, monkeypatch):
        """Reply without credentials returns error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = reply_email_fn(message_id="msg_123", html="<p>Reply</p>")

        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]

    def test_empty_message_id(self, reply_email_fn, monkeypatch):
        """Empty message_id returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = reply_email_fn(message_id="", html="<p>Reply</p>")

        assert "error" in result
        assert "message_id" in result["error"]

    def test_empty_html(self, reply_email_fn, monkeypatch):
        """Empty html body returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        result = reply_email_fn(message_id="msg_123", html="")

        assert "error" in result
        assert "body" in result["error"].lower() or "html" in result["error"].lower()

    def test_original_message_not_found(self, reply_email_fn, monkeypatch):
        """404 when fetching original message returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch(_HTTPX_GET, return_value=mock_resp):
            result = reply_email_fn(message_id="nonexistent", html="<p>Reply</p>")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_successful_reply(self, reply_email_fn, monkeypatch):
        """Successful reply returns success with threadId."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        mock_get_resp = _mock_original_message_response()
        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 200
        mock_send_resp.json.return_value = {"id": "reply_456", "threadId": "thread_abc"}

        with patch(_HTTPX_GET, return_value=mock_get_resp):
            with patch(_HTTPX_POST, return_value=mock_send_resp) as mock_post:
                result = reply_email_fn(message_id="orig_123", html="<p>My reply</p>")

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["id"] == "reply_456"
        assert result["threadId"] == "thread_abc"
        assert result["to"] == "sender@example.com"
        assert result["subject"] == "Re: Hello there"

        # Verify threadId was sent in the request body
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["threadId"] == "thread_abc"
        assert "raw" in call_kwargs[1]["json"]

    def test_reply_preserves_existing_re_prefix(self, reply_email_fn, monkeypatch):
        """Subject already starting with Re: is not double-prefixed."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {
            "id": "orig_re",
            "threadId": "thread_re",
            "payload": {
                "headers": [
                    {"name": "Message-ID", "value": "<re@mail.gmail.com>"},
                    {"name": "Subject", "value": "Re: Already replied"},
                    {"name": "From", "value": "sender@example.com"},
                ]
            },
        }

        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 200
        mock_send_resp.json.return_value = {"id": "reply_re", "threadId": "thread_re"}

        with patch(_HTTPX_GET, return_value=mock_get_resp):
            with patch(_HTTPX_POST, return_value=mock_send_resp):
                result = reply_email_fn(message_id="orig_re", html="<p>Reply</p>")

        assert result["subject"] == "Re: Already replied"

    def test_reply_with_cc(self, reply_email_fn, monkeypatch):
        """Reply with CC recipients includes them in the message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        mock_get_resp = _mock_original_message_response()
        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 200
        mock_send_resp.json.return_value = {"id": "reply_cc", "threadId": "thread_abc"}

        with patch(_HTTPX_GET, return_value=mock_get_resp):
            with patch(_HTTPX_POST, return_value=mock_send_resp) as mock_post:
                result = reply_email_fn(
                    message_id="orig_123",
                    html="<p>Reply with CC</p>",
                    cc=["cc@example.com"],
                )

        assert result["success"] is True
        # Verify the raw message was sent (CC is embedded in the MIME message)
        assert "raw" in mock_post.call_args[1]["json"]

    def test_send_401_returns_token_error(self, reply_email_fn, monkeypatch):
        """401 on send returns token expired error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "expired_token")

        mock_get_resp = _mock_original_message_response()
        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 401

        with patch(_HTTPX_GET, return_value=mock_get_resp):
            with patch(_HTTPX_POST, return_value=mock_send_resp):
                result = reply_email_fn(message_id="orig_123", html="<p>Reply</p>")

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()

    def test_send_api_error(self, reply_email_fn, monkeypatch):
        """Non-200 on send returns API error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")

        mock_get_resp = _mock_original_message_response()
        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 403
        mock_send_resp.text = "Insufficient permissions"

        with patch(_HTTPX_GET, return_value=mock_get_resp):
            with patch(_HTTPX_POST, return_value=mock_send_resp):
                result = reply_email_fn(message_id="orig_123", html="<p>Reply</p>")

        assert "error" in result
        assert "403" in result["error"]
