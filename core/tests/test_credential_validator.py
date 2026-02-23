"""Unit tests for the pre-flight credential validator.

Tests cover:
- Missing credential detection
- Invalid key format detection
- Valid credential pass-through
- Model-to-provider mapping
- Multi-provider validation
- Error message formatting
- CredentialIssue.to_exception()

Resolves: https://github.com/aden-hive/hive/issues/4391
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure framework is importable
_core_dir = Path(__file__).resolve().parent.parent
if str(_core_dir) not in sys.path:
    sys.path.insert(0, str(_core_dir))

from framework.credentials.validator import (
    CredentialIssue,
    CredentialValidator,
)


# ── Missing credential detection ─────────────────────────────────────────


class TestMissingCredential:
    """Tests that missing credentials are properly detected."""

    def test_missing_anthropic_key(self, monkeypatch):
        """Verify missing ANTHROPIC_API_KEY is detected."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate("anthropic")

        assert error is not None
        assert error.error_type == "missing"
        assert error.env_var == "ANTHROPIC_API_KEY"
        assert error.provider == "Anthropic"

    def test_missing_openai_key(self, monkeypatch):
        """Verify missing OPENAI_API_KEY is detected."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        error = CredentialValidator.validate("openai")

        assert error is not None
        assert error.error_type == "missing"
        assert error.env_var == "OPENAI_API_KEY"

    def test_empty_string_key_is_missing(self, monkeypatch):
        """Verify that an empty string API key is treated as missing."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")

        error = CredentialValidator.validate("anthropic")

        assert error is not None
        assert error.error_type == "missing"

    def test_whitespace_only_key_is_missing(self, monkeypatch):
        """Verify that a whitespace-only API key is treated as missing."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")

        error = CredentialValidator.validate("anthropic")

        assert error is not None
        assert error.error_type == "missing"


# ── Invalid key format detection ──────────────────────────────────────────


class TestInvalidCredential:
    """Tests that incorrectly formatted credentials are flagged."""

    def test_invalid_anthropic_key_format(self, monkeypatch):
        """Verify invalid Anthropic key format is detected."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "invalid-key-123")

        error = CredentialValidator.validate("anthropic")

        assert error is not None
        assert error.error_type == "invalid"

    def test_invalid_openai_key_format(self, monkeypatch):
        """Verify invalid OpenAI key format is detected."""
        monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")

        error = CredentialValidator.validate("openai")

        assert error is not None
        assert error.error_type == "invalid"

    def test_invalid_groq_key_format(self, monkeypatch):
        """Verify invalid Groq key format is detected."""
        monkeypatch.setenv("GROQ_API_KEY", "not-gsk-key")

        error = CredentialValidator.validate("groq")

        assert error is not None
        assert error.error_type == "invalid"


# ── Valid credential pass-through ─────────────────────────────────────────


class TestValidCredential:
    """Tests that properly formatted credentials pass validation."""

    def test_valid_anthropic_key(self, monkeypatch):
        """Verify valid Anthropic key passes validation."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "a" * 95)

        error = CredentialValidator.validate("anthropic")

        assert error is None

    def test_valid_openai_key(self, monkeypatch):
        """Verify valid OpenAI key passes validation."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 48)

        error = CredentialValidator.validate("openai")

        assert error is None

    def test_valid_groq_key(self, monkeypatch):
        """Verify valid Groq key passes validation."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 40)

        error = CredentialValidator.validate("groq")

        assert error is None

    def test_unknown_provider_returns_none(self):
        """Verify unknown providers return None (skip validation)."""
        error = CredentialValidator.validate("totally_unknown_provider")

        assert error is None


# ── Model-to-provider mapping ────────────────────────────────────────────


class TestModelProviderMapping:
    """Tests that model names are correctly mapped to providers."""

    @pytest.mark.parametrize(
        "model,expected_provider",
        [
            ("claude-3-haiku-20240307", "anthropic"),
            ("claude-3-opus", "anthropic"),
            ("claude-haiku-4-5-20251001", "anthropic"),
            ("gpt-4o-mini", "openai"),
            ("gpt-4-turbo", "openai"),
            ("o1-mini", "openai"),
            ("gemini/gemini-1.5-flash", "gemini"),
            ("gemini-pro", "gemini"),
            ("groq/llama3-70b", "groq"),
            ("deepseek/deepseek-chat", "deepseek"),
            ("mistral-large", "mistral"),
        ],
    )
    def test_model_to_provider(self, model, expected_provider):
        """Verify model name maps to the correct provider."""
        provider = CredentialValidator.get_provider_for_model(model)
        assert provider == expected_provider

    def test_unknown_model_returns_none(self):
        """Verify unknown model returns None."""
        provider = CredentialValidator.get_provider_for_model("some-random-model")
        assert provider is None

    def test_validate_for_model_missing_key(self, monkeypatch):
        """Verify validate_for_model catches missing keys."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate_for_model("claude-3-haiku-20240307")

        assert error is not None
        assert error.error_type == "missing"
        assert "ANTHROPIC_API_KEY" in error.format_message()

    def test_validate_for_model_unknown_model(self):
        """Verify validate_for_model returns None for unknown models."""
        error = CredentialValidator.validate_for_model("some-random-model")
        assert error is None


# ── Multi-provider validation ─────────────────────────────────────────────


class TestMultiProviderValidation:
    """Tests for validating multiple providers at once."""

    def test_validate_multiple_all_missing(self, monkeypatch):
        """Verify all missing credentials are detected."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        issues = CredentialValidator.validate_multiple(["anthropic", "openai"])

        assert len(issues) == 2
        providers = {i.provider for i in issues}
        assert "Anthropic" in providers
        assert "OpenAI" in providers

    def test_validate_multiple_partial(self, monkeypatch):
        """Verify only missing credentials are flagged when some are set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "a" * 95)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        issues = CredentialValidator.validate_multiple(["anthropic", "openai"])

        assert len(issues) == 1
        assert issues[0].provider == "OpenAI"

    def test_validate_multiple_all_valid(self, monkeypatch):
        """Verify no issues when all credentials are valid."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "a" * 95)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 48)

        issues = CredentialValidator.validate_multiple(["anthropic", "openai"])

        assert len(issues) == 0


# ── Error message formatting ─────────────────────────────────────────────


class TestErrorMessageFormatting:
    """Tests for human-readable error message content."""

    def test_missing_message_contains_env_var(self, monkeypatch):
        """Verify the missing error message contains the env var name."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate("anthropic")
        message = error.format_message()

        assert "ANTHROPIC_API_KEY" in message

    def test_missing_message_contains_console_url(self, monkeypatch):
        """Verify the missing error message contains the provider URL."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate("anthropic")
        message = error.format_message()

        assert "console.anthropic.com" in message

    def test_missing_message_contains_export_command(self, monkeypatch):
        """Verify the missing error message contains the export command."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate("anthropic")
        message = error.format_message()

        assert "export ANTHROPIC_API_KEY" in message

    def test_missing_message_contains_doctor_hint(self, monkeypatch):
        """Verify the missing error message mentions hive doctor."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        error = CredentialValidator.validate("anthropic")
        message = error.format_message()

        assert "hive doctor" in message

    def test_invalid_message_contains_format_hint(self, monkeypatch):
        """Verify the invalid error message mentions expected format."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")

        error = CredentialValidator.validate("anthropic")
        message = error.format_message()

        assert "Invalid" in message or "invalid" in message
        assert "ANTHROPIC_API_KEY" in message

    def test_expired_message_formatting(self):
        """Verify the expired error message formatting."""
        issue = CredentialIssue(
            provider="TestProvider",
            env_var="TEST_API_KEY",
            error_type="expired",
            console_url="https://example.com/keys",
            config_example='{"key": "value"}',
        )
        message = issue.format_message()

        assert "Expired" in message or "expired" in message
        assert "TEST_API_KEY" in message
        assert "example.com" in message


# ── CredentialIssue.to_exception ──────────────────────────────────────────


class TestCredentialIssueToException:
    """Tests for converting CredentialIssue to CredentialError."""

    def test_to_exception_returns_credential_error(self, monkeypatch):
        """Verify to_exception returns a CredentialError."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from framework.credentials.models import CredentialError

        error = CredentialValidator.validate("anthropic")
        exc = error.to_exception()

        assert isinstance(exc, CredentialError)
        assert "ANTHROPIC_API_KEY" in str(exc)

    def test_to_exception_is_raisable(self, monkeypatch):
        """Verify the exception can be raised and caught."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from framework.credentials.models import CredentialError

        error = CredentialValidator.validate("openai")

        with pytest.raises(CredentialError, match="OPENAI_API_KEY"):
            raise error.to_exception()


# ── Format multiple issues ────────────────────────────────────────────────


class TestFormatMultipleIssues:
    """Tests for formatting multiple credential issues together."""

    def test_format_empty_list(self):
        """Verify empty issues list returns empty string."""
        result = CredentialValidator.format_multiple_issues([])
        assert result == ""

    def test_format_multiple_includes_count(self, monkeypatch):
        """Verify multiple issues are formatted with a count header."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        issues = CredentialValidator.validate_multiple(["anthropic", "openai"])
        result = CredentialValidator.format_multiple_issues(issues)

        assert "2 Credential Issue(s) Found" in result
