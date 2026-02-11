"""Tests for email tool with multi-provider support (FastMCP)."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.email_tool import register_tools


@pytest.fixture
def send_email_fn(mcp: FastMCP):
    """Register and return the send_email tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["send_email"].fn


class TestSendEmail:
    """Tests for send_email tool."""

    def test_no_credentials_returns_error(self, send_email_fn, monkeypatch):
        """Send without credentials returns helpful error."""
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
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

        result = send_email_fn(to="test@example.com", subject="", html="<p>Hi</p>", provider="resend")

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

        patch_target = "aden_tools.tools.email_tool.email_tool.httpx.post"
        with patch(patch_target, return_value=mock_response) as mock_post:
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

        with patch("aden_tools.tools.email_tool.email_tool.httpx.post", return_value=mock_response):
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

        with patch("aden_tools.tools.email_tool.email_tool.httpx.post", return_value=mock_response):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="gmail",
            )

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
        assert "help" in result

    def test_gmail_no_from_email_ok(self, send_email_fn, monkeypatch):
        """Gmail works without from_email (defaults to authenticated user)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_gmail_token")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "gmail_no_from"}

        with patch("aden_tools.tools.email_tool.email_tool.httpx.post", return_value=mock_response):
            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="gmail",
            )

        assert result["success"] is True
        assert result["provider"] == "gmail"


class TestProviderRequired:
    """Tests that provider is a required parameter."""

    def test_missing_provider_raises_type_error(self, send_email_fn):
        """Calling send_email without provider raises TypeError."""
        with pytest.raises(TypeError):
            send_email_fn(to="test@example.com", subject="Test", html="<p>Hi</p>")
