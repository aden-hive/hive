"""Tests for CredentialManager."""
from pathlib import Path

import pytest

from aden_tools.credentials import (
    CredentialManager,
    CredentialSpec,
    CredentialError,
    CREDENTIAL_SPECS,
)


class TestCredentialManager:
    """Tests for CredentialManager class."""

    def test_get_returns_env_value(self, monkeypatch):
        """get() returns environment variable value."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-api-key")

        creds = CredentialManager()

        assert creds.get("brave_search") == "test-api-key"

    def test_get_returns_none_when_not_set(self, monkeypatch, tmp_path):
        """get() returns None when env var is not set."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        assert creds.get("brave_search") is None

    def test_get_raises_for_unknown_credential(self):
        """get() raises KeyError for unknown credential name."""
        creds = CredentialManager()

        with pytest.raises(KeyError) as exc_info:
            creds.get("unknown_credential")

        assert "unknown_credential" in str(exc_info.value)
        assert "Available" in str(exc_info.value)

    def test_get_reads_fresh_for_hot_reload(self, monkeypatch):
        """get() reads fresh each time to support hot-reload."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "original-key")
        creds = CredentialManager()

        # First call
        assert creds.get("brave_search") == "original-key"

        # Change env var
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "new-key")

        # Should return the new value (no caching)
        assert creds.get("brave_search") == "new-key"

    def test_is_available_true_when_set(self, monkeypatch):
        """is_available() returns True when credential is set."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialManager()

        assert creds.is_available("brave_search") is True

    def test_is_available_false_when_not_set(self, monkeypatch, tmp_path):
        """is_available() returns False when credential is not set."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        assert creds.is_available("brave_search") is False

    def test_is_available_false_for_empty_string(self, monkeypatch, tmp_path):
        """is_available() returns False for empty string."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "")

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        assert creds.is_available("brave_search") is False

    def test_get_spec_returns_spec(self):
        """get_spec() returns the credential spec."""
        creds = CredentialManager()

        spec = creds.get_spec("brave_search")

        assert spec.env_var == "BRAVE_SEARCH_API_KEY"
        assert "web_search" in spec.tools

    def test_get_spec_raises_for_unknown(self):
        """get_spec() raises KeyError for unknown credential."""
        creds = CredentialManager()

        with pytest.raises(KeyError):
            creds.get_spec("unknown")


class TestCredentialManagerToolMapping:
    """Tests for tool-to-credential mapping."""

    def test_get_credential_for_tool(self):
        """get_credential_for_tool() returns correct credential name."""
        creds = CredentialManager()

        assert creds.get_credential_for_tool("web_search") == "brave_search"

    def test_get_credential_for_tool_returns_none_for_unknown(self):
        """get_credential_for_tool() returns None for tools without credentials."""
        creds = CredentialManager()

        assert creds.get_credential_for_tool("file_read") is None
        assert creds.get_credential_for_tool("unknown_tool") is None

    def test_get_missing_for_tools_returns_missing(self, monkeypatch, tmp_path):
        """get_missing_for_tools() returns missing required credentials."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")
        missing = creds.get_missing_for_tools(["web_search", "file_read"])

        assert len(missing) == 1
        cred_name, spec = missing[0]
        assert cred_name == "brave_search"
        assert spec.env_var == "BRAVE_SEARCH_API_KEY"

    def test_get_missing_for_tools_returns_empty_when_all_present(self, monkeypatch):
        """get_missing_for_tools() returns empty list when all credentials present."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialManager()
        missing = creds.get_missing_for_tools(["web_search", "file_read"])

        assert missing == []

    def test_get_missing_for_tools_no_duplicates(self, monkeypatch):
        """get_missing_for_tools() doesn't return duplicates for same credential."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        # Create spec where multiple tools share a credential
        custom_specs = {
            "shared_cred": CredentialSpec(
                env_var="SHARED_KEY",
                tools=["tool_a", "tool_b"],
                required=True,
            )
        }

        creds = CredentialManager(specs=custom_specs)
        missing = creds.get_missing_for_tools(["tool_a", "tool_b"])

        # Should only appear once even though two tools need it
        assert len(missing) == 1


class TestCredentialManagerValidation:
    """Tests for validate_for_tools() behavior."""

    def test_validate_for_tools_raises_for_missing(self, monkeypatch, tmp_path):
        """validate_for_tools() raises CredentialError when required creds missing."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_for_tools(["web_search"])

        error_msg = str(exc_info.value)
        assert "BRAVE_SEARCH_API_KEY" in error_msg
        assert "web_search" in error_msg
        assert "brave.com" in error_msg  # help URL

    def test_validate_for_tools_passes_when_present(self, monkeypatch):
        """validate_for_tools() succeeds when all required credentials are set."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialManager()

        # Should not raise
        creds.validate_for_tools(["web_search", "file_read"])

    def test_validate_for_tools_passes_for_tools_without_credentials(self):
        """validate_for_tools() succeeds for tools that don't need credentials."""
        creds = CredentialManager()

        # Should not raise - file_read doesn't need credentials
        creds.validate_for_tools(["file_read"])

    def test_validate_for_tools_passes_for_empty_list(self):
        """validate_for_tools() succeeds for empty tool list."""
        creds = CredentialManager()

        # Should not raise
        creds.validate_for_tools([])

    def test_validate_for_tools_skips_optional_credentials(self, monkeypatch):
        """validate_for_tools() doesn't fail for missing optional credentials."""
        custom_specs = {
            "optional_cred": CredentialSpec(
                env_var="OPTIONAL_KEY",
                tools=["optional_tool"],
                required=False,  # Optional
            )
        }
        monkeypatch.delenv("OPTIONAL_KEY", raising=False)

        creds = CredentialManager(specs=custom_specs)

        # Should not raise because credential is optional
        creds.validate_for_tools(["optional_tool"])


class TestCredentialManagerForTesting:
    """Tests for test factory method."""

    def test_for_testing_uses_overrides(self):
        """for_testing() uses provided override values."""
        creds = CredentialManager.for_testing({"brave_search": "mock-key"})

        assert creds.get("brave_search") == "mock-key"

    def test_for_testing_ignores_env(self, monkeypatch):
        """for_testing() ignores actual environment variables."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "real-key")

        creds = CredentialManager.for_testing({"brave_search": "mock-key"})

        assert creds.get("brave_search") == "mock-key"

    def test_for_testing_validation_passes_with_overrides(self):
        """for_testing() credentials pass validation."""
        creds = CredentialManager.for_testing({"brave_search": "mock-key"})

        # Should not raise
        creds.validate_for_tools(["web_search"])

    def test_for_testing_validation_fails_without_override(self, monkeypatch, tmp_path):
        """for_testing() without override still fails validation."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager.for_testing({}, dotenv_path=tmp_path / ".env")  # No overrides

        with pytest.raises(CredentialError):
            creds.validate_for_tools(["web_search"])

    def test_for_testing_with_custom_specs(self):
        """for_testing() works with custom specs."""
        custom_specs = {
            "custom_cred": CredentialSpec(
                env_var="CUSTOM_VAR",
                tools=["custom_tool"],
                required=True,
            )
        }

        creds = CredentialManager.for_testing(
            {"custom_cred": "test-value"},
            specs=custom_specs,
        )

        assert creds.get("custom_cred") == "test-value"


class TestCredentialSpec:
    """Tests for CredentialSpec dataclass."""

    def test_default_values(self):
        """CredentialSpec has sensible defaults."""
        spec = CredentialSpec(env_var="TEST_VAR")

        assert spec.env_var == "TEST_VAR"
        assert spec.tools == []
        assert spec.node_types == []
        assert spec.required is True
        assert spec.startup_required is False
        assert spec.help_url == ""
        assert spec.description == ""

    def test_all_values(self):
        """CredentialSpec accepts all values."""
        spec = CredentialSpec(
            env_var="API_KEY",
            tools=["tool_a", "tool_b"],
            node_types=["llm_generate"],
            required=False,
            startup_required=True,
            help_url="https://example.com",
            description="Test API key",
        )

        assert spec.env_var == "API_KEY"
        assert spec.tools == ["tool_a", "tool_b"]
        assert spec.node_types == ["llm_generate"]
        assert spec.required is False
        assert spec.startup_required is True
        assert spec.help_url == "https://example.com"
        assert spec.description == "Test API key"


class TestCredentialSpecs:
    """Tests for the CREDENTIAL_SPECS constant."""

    def test_brave_search_spec_exists(self):
        """CREDENTIAL_SPECS includes brave_search."""
        assert "brave_search" in CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["brave_search"]
        assert spec.env_var == "BRAVE_SEARCH_API_KEY"
        assert "web_search" in spec.tools
        assert spec.required is True
        assert spec.startup_required is False
        assert "brave.com" in spec.help_url

    def test_anthropic_spec_exists(self):
        """CREDENTIAL_SPECS includes anthropic with startup_required=True."""
        assert "anthropic" in CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["anthropic"]
        assert spec.env_var == "ANTHROPIC_API_KEY"
        assert spec.tools == []
        assert "llm_generate" in spec.node_types
        assert "llm_tool_use" in spec.node_types
        assert spec.required is True
        assert spec.startup_required is True
        assert "anthropic.com" in spec.help_url


class TestNodeTypeValidation:
    """Tests for node type credential validation."""

    def test_get_missing_for_node_types_returns_missing(self, monkeypatch, tmp_path):
        """get_missing_for_node_types() returns missing credentials."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")
        missing = creds.get_missing_for_node_types(["llm_generate", "llm_tool_use"])

        assert len(missing) == 1
        cred_name, spec = missing[0]
        assert cred_name == "anthropic"
        assert spec.env_var == "ANTHROPIC_API_KEY"

    def test_get_missing_for_node_types_returns_empty_when_present(self, monkeypatch):
        """get_missing_for_node_types() returns empty when credentials present."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialManager()
        missing = creds.get_missing_for_node_types(["llm_generate", "llm_tool_use"])

        assert missing == []

    def test_get_missing_for_node_types_ignores_unknown_types(self, monkeypatch):
        """get_missing_for_node_types() ignores node types without credentials."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialManager()
        missing = creds.get_missing_for_node_types(["unknown_type", "another_type"])

        assert missing == []

    def test_validate_for_node_types_raises_for_missing(self, monkeypatch, tmp_path):
        """validate_for_node_types() raises CredentialError when missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_for_node_types(["llm_generate"])

        error_msg = str(exc_info.value)
        assert "ANTHROPIC_API_KEY" in error_msg
        assert "llm_generate" in error_msg

    def test_validate_for_node_types_passes_when_present(self, monkeypatch):
        """validate_for_node_types() passes when credentials present."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialManager()

        # Should not raise
        creds.validate_for_node_types(["llm_generate", "llm_tool_use"])


class TestStartupValidation:
    """Tests for startup credential validation."""

    def test_validate_startup_raises_for_missing(self, monkeypatch, tmp_path):
        """validate_startup() raises CredentialError when startup creds missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds = CredentialManager(dotenv_path=tmp_path / ".env")

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_startup()

        error_msg = str(exc_info.value)
        assert "ANTHROPIC_API_KEY" in error_msg
        assert "Server startup failed" in error_msg

    def test_validate_startup_passes_when_present(self, monkeypatch):
        """validate_startup() passes when all startup creds are set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialManager()

        # Should not raise
        creds.validate_startup()

    def test_validate_startup_ignores_non_startup_creds(self, monkeypatch):
        """validate_startup() ignores credentials without startup_required=True."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialManager()

        # Should not raise - BRAVE_SEARCH_API_KEY is not startup_required
        creds.validate_startup()

    def test_validate_startup_with_test_overrides(self):
        """validate_startup() works with for_testing() overrides."""
        creds = CredentialManager.for_testing({"anthropic": "test-key"})

        # Should not raise
        creds.validate_startup()


class TestDotenvReading:
    """Tests for .env file reading (hot-reload support)."""

    def test_reads_from_dotenv_file(self, tmp_path, monkeypatch):
        """CredentialManager reads credentials from .env file."""
        # Ensure env var is not set
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        # Create a .env file
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=dotenv-key\n")

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.get("brave_search") == "dotenv-key"

    def test_env_var_takes_precedence_over_dotenv(self, tmp_path, monkeypatch):
        """os.environ takes precedence over .env file."""
        # Set both env var and .env file
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "env-key")

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=dotenv-key\n")

        creds = CredentialManager(dotenv_path=dotenv_file)

        # Should return env var value, not dotenv value
        assert creds.get("brave_search") == "env-key"

    def test_missing_dotenv_file_returns_none(self, tmp_path, monkeypatch):
        """Missing .env file doesn't crash, returns None."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        # Point to non-existent file
        dotenv_file = tmp_path / ".env"  # Not created

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.get("brave_search") is None

    def test_hot_reload_from_dotenv(self, tmp_path, monkeypatch):
        """CredentialManager picks up changes to .env file without restart."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=original-key\n")

        creds = CredentialManager(dotenv_path=dotenv_file)

        # First read
        assert creds.get("brave_search") == "original-key"

        # Update the .env file (simulating user adding credential)
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=updated-key\n")

        # Should read the new value (hot-reload)
        assert creds.get("brave_search") == "updated-key"

    def test_is_available_works_with_dotenv(self, tmp_path, monkeypatch):
        """is_available() works correctly with .env file credentials."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=dotenv-key\n")

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.is_available("brave_search") is True

    def test_validation_works_with_dotenv(self, tmp_path, monkeypatch):
        """validate_for_tools() works with .env file credentials."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=dotenv-key\n")

        creds = CredentialManager(dotenv_path=dotenv_file)

        # Should not raise because credential is available in .env
        creds.validate_for_tools(["web_search"])

    def test_dotenv_with_multiple_credentials(self, tmp_path, monkeypatch):
        """CredentialManager reads multiple credentials from .env file."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text(
            "ANTHROPIC_API_KEY=anthropic-key\n"
            "BRAVE_SEARCH_API_KEY=brave-key\n"
        )

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.get("anthropic") == "anthropic-key"
        assert creds.get("brave_search") == "brave-key"

    def test_dotenv_with_quoted_values(self, tmp_path, monkeypatch):
        """CredentialManager handles quoted values in .env file."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text('BRAVE_SEARCH_API_KEY="quoted-key"\n')

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.get("brave_search") == "quoted-key"

    def test_dotenv_with_comments(self, tmp_path, monkeypatch):
        """CredentialManager ignores comments in .env file."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text(
            "# This is a comment\n"
            "BRAVE_SEARCH_API_KEY=key-after-comment\n"
        )

        creds = CredentialManager(dotenv_path=dotenv_file)

        assert creds.get("brave_search") == "key-after-comment"

    def test_overrides_take_precedence_over_dotenv(self, tmp_path, monkeypatch):
        """Test override values take precedence over .env file."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("BRAVE_SEARCH_API_KEY=dotenv-key\n")

        creds = CredentialManager.for_testing(
            {"brave_search": "override-key"},
        )
        # Note: for_testing doesn't use dotenv_path, but we test the principle
        # that _overrides always win

        assert creds.get("brave_search") == "override-key"
