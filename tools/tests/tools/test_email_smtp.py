"""Tests for SMTP email provider functionality."""

from unittest.mock import MagicMock, patch

from fastmcp import FastMCP

from aden_tools.tools.email_tool import register_tools


class TestSMTPProvider:
    """Tests for SMTP email provider."""

    def test_smtp_success(self, monkeypatch):
        """Successful SMTP send returns success dict."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "app_password")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "bot@example.com")

        mcp = FastMCP("test-server")

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_smtp_instance = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_smtp_instance

            register_tools(mcp)
            send_email_fn = mcp._tool_manager._tools["send_email"].fn

            result = send_email_fn(
                to="test@example.com",
                subject="Test SMTP",
                html="<p>Hello from SMTP</p>",
                provider="smtp",
            )

        assert result["success"] is True
        assert result["provider"] == "smtp"
        assert result["to"] == ["test@example.com"]
        assert result["subject"] == "Test SMTP"

        # Verify SMTP connection
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("bot@example.com", "app_password")
        mock_smtp_instance.send_message.assert_called_once()

    def test_smtp_missing_credentials(self, monkeypatch):
        """Explicit SMTP provider without credentials returns error."""
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "test@example.com")

        mcp = FastMCP("test-server")
        register_tools(mcp)
        send_email_fn = mcp._tool_manager._tools["send_email"].fn

        result = send_email_fn(
            to="test@example.com",
            subject="Test",
            html="<p>Hi</p>",
            provider="smtp",
        )

        assert "error" in result
        assert "SMTP credentials not configured" in result["error"]

    def test_smtp_connection_error(self, monkeypatch):
        """SMTP connection error returns error dict."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "app_password")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "bot@example.com")

        mcp = FastMCP("test-server")

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("Connection refused")

            register_tools(mcp)
            send_email_fn = mcp._tool_manager._tools["send_email"].fn

            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                provider="smtp",
            )

        assert "error" in result
        assert "SMTP send failed" in result["error"]

    def test_auto_falls_back_to_smtp(self, monkeypatch):
        """Auto mode falls back to SMTP when Gmail and Resend are not available."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "app_password")
        monkeypatch.setenv("EMAIL_FROM", "bot@example.com")

        mcp = FastMCP("test-server")

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_smtp_instance = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_smtp_instance

            register_tools(mcp)
            send_email_fn = mcp._tool_manager._tools["send_email"].fn

            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
            )

        assert result["success"] is True
        assert result["provider"] == "smtp"
        mock_smtp_instance.send_message.assert_called_once()

    def test_smtp_with_cc_bcc(self, monkeypatch):
        """SMTP handles CC and BCC correctly."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "app_password")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("EMAIL_FROM", "bot@example.com")

        mcp = FastMCP("test-server")

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_smtp_instance = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_smtp_instance

            register_tools(mcp)
            send_email_fn = mcp._tool_manager._tools["send_email"].fn

            result = send_email_fn(
                to="test@example.com",
                subject="Test",
                html="<p>Hi</p>",
                cc="cc@example.com",
                bcc=["bcc1@example.com", "bcc2@example.com"],
                provider="smtp",
            )

        assert result["success"] is True
        # Verify the message was sent (cc/bcc are not in returned dict but are in MIME message)
        mock_smtp_instance.send_message.assert_called_once()
