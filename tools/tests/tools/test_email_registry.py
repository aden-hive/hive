"""Tests for the Email Provider Registry."""

from unittest.mock import MagicMock
import pytest

from aden_tools.tools.email_tool.registry import ProviderRegistry
from aden_tools.tools.email_tool.providers.mock import MockEmailProvider
from aden_tools.tools.email_tool.providers.gmail import GmailEmailProvider
from aden_tools.tools.email_tool.providers.resend import ResendEmailProvider


class TestProviderRegistry:

    def test_explicit_mock_provider(self):
        reg = ProviderRegistry()
        provider = reg.get_provider("mock")
        assert isinstance(provider, MockEmailProvider)
        assert provider.provider_id == "mock"

    def test_explicit_gmail_provider(self, monkeypatch):
        # Even without credentials in the env, getting a specific provider explicitly instantiates it
        reg = ProviderRegistry()
        provider = reg.get_provider("gmail")
        assert isinstance(provider, GmailEmailProvider)

    def test_explicit_resend_provider(self):
        reg = ProviderRegistry()
        provider = reg.get_provider("resend")
        assert isinstance(provider, ResendEmailProvider)

    def test_invalid_provider_raises_error(self):
        reg = ProviderRegistry()
        with pytest.raises(ValueError, match="is not currently configured or supported"):
            reg.get_provider("invalid_provider")

    def test_infer_provider_gmail_priority(self, monkeypatch):
        # If both are present, gmail takes priority for "auto"
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "fake_token")
        monkeypatch.setenv("RESEND_API_KEY", "fake_key")
        
        reg = ProviderRegistry()
        provider = reg.get_provider("auto")
        assert isinstance(provider, GmailEmailProvider)

    def test_infer_provider_resend_fallback(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("RESEND_API_KEY", "fake_key")
        
        reg = ProviderRegistry()
        provider = reg.get_provider("auto")
        assert isinstance(provider, ResendEmailProvider)

    def test_infer_provider_mock_fallback(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        
        reg = ProviderRegistry()
        provider = reg.get_provider("auto")
        assert isinstance(provider, MockEmailProvider)

    def test_infer_provider_with_credential_store(self):
        mock_credentials = MagicMock()
        mock_credentials.get.side_effect = lambda key: "fake_token" if key == "google" else None
        
        reg = ProviderRegistry(credentials=mock_credentials)
        provider = reg.get_provider("auto")
        assert isinstance(provider, GmailEmailProvider)
