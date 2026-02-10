"""Tests for CredentialStoreAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.credentials import (
    CREDENTIAL_SPECS,
    CredentialError,
    CredentialSpec,
    CredentialStoreAdapter,
)


@pytest.fixture(autouse=True)
def _no_dotenv(tmp_path, monkeypatch):
    """Isolate tests from the project .env file.

    EnvVarStorage falls back to reading Path.cwd()/.env when a key is
    missing from os.environ.  Changing cwd to a temp dir ensures
    monkeypatch.delenv() truly simulates a missing credential.
    """
    monkeypatch.chdir(tmp_path)


class TestCredentialStoreAdapter:
    """Tests for CredentialStoreAdapter class."""

    def test_get_returns_env_value(self, monkeypatch):
        """get() returns environment variable value."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-api-key")

        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.get("brave_search") == "test-api-key"

    def test_get_returns_none_when_not_set(self, monkeypatch):
        """get() returns None when env var is not set."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.get("brave_search") is None

    def test_get_raises_for_unknown_credential(self):
        """get() raises KeyError for unknown credential name."""
        creds = CredentialStoreAdapter.with_env_storage()

        with pytest.raises(KeyError) as exc_info:
            creds.get("unknown_credential")

        assert "unknown_credential" in str(exc_info.value)
        assert "Available" in str(exc_info.value)

    def test_is_available_true_when_set(self, monkeypatch):
        """is_available() returns True when credential is set."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.is_available("brave_search") is True

    def test_is_available_false_when_not_set(self, monkeypatch):
        """is_available() returns False when credential is not set."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.is_available("brave_search") is False

    def test_is_available_false_for_empty_string(self, monkeypatch):
        """is_available() returns False for empty string."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "")

        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.is_available("brave_search") is False

    def test_get_spec_returns_spec(self):
        """get_spec() returns the credential spec."""
        creds = CredentialStoreAdapter.with_env_storage()

        spec = creds.get_spec("brave_search")

        assert spec.env_var == "BRAVE_SEARCH_API_KEY"
        assert "web_search" in spec.tools

    def test_get_spec_raises_for_unknown(self):
        """get_spec() raises KeyError for unknown credential."""
        creds = CredentialStoreAdapter.with_env_storage()

        with pytest.raises(KeyError):
            creds.get_spec("unknown")


class TestCredentialStoreAdapterToolMapping:
    """Tests for tool-to-credential mapping."""

    def test_get_credential_for_tool(self):
        """get_credential_for_tool() returns correct credential name."""
        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.get_credential_for_tool("web_search") == "brave_search"

    def test_get_credential_for_tool_returns_none_for_unknown(self):
        """get_credential_for_tool() returns None for tools without credentials."""
        creds = CredentialStoreAdapter.with_env_storage()

        assert creds.get_credential_for_tool("file_read") is None
        assert creds.get_credential_for_tool("unknown_tool") is None

    def test_get_missing_for_tools_returns_missing(self, monkeypatch):
        """get_missing_for_tools() returns missing required credentials."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.with_env_storage()
        missing = creds.get_missing_for_tools(["web_search", "file_read"])

        assert len(missing) == 1
        cred_name, spec = missing[0]
        assert cred_name == "brave_search"
        assert spec.env_var == "BRAVE_SEARCH_API_KEY"

    def test_get_missing_for_tools_returns_empty_when_all_present(self, monkeypatch):
        """get_missing_for_tools() returns empty list when all credentials present."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()
        missing = creds.get_missing_for_tools(["web_search", "file_read"])

        assert missing == []

    def test_get_missing_for_tools_no_duplicates(self, monkeypatch):
        """get_missing_for_tools() doesn't return duplicates for same credential."""
        monkeypatch.delenv("SHARED_KEY", raising=False)

        # Create spec where multiple tools share a credential
        custom_specs = {
            "shared_cred": CredentialSpec(
                env_var="SHARED_KEY",
                tools=["tool_a", "tool_b"],
                required=True,
            )
        }

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)
        missing = creds.get_missing_for_tools(["tool_a", "tool_b"])

        # Should only appear once even though two tools need it
        assert len(missing) == 1


class TestCredentialStoreAdapterValidation:
    """Tests for validate_for_tools() behavior."""

    def test_validate_for_tools_raises_for_missing(self, monkeypatch):
        """validate_for_tools() raises CredentialError when required creds missing."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.with_env_storage()

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_for_tools(["web_search"])

        error_msg = str(exc_info.value)
        assert "BRAVE_SEARCH_API_KEY" in error_msg
        assert "web_search" in error_msg
        assert "brave.com" in error_msg  # help URL

    def test_validate_for_tools_passes_when_present(self, monkeypatch):
        """validate_for_tools() succeeds when all required credentials are set."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()

        # Should not raise
        creds.validate_for_tools(["web_search", "file_read"])

    def test_validate_for_tools_passes_for_tools_without_credentials(self):
        """validate_for_tools() succeeds for tools that don't need credentials."""
        creds = CredentialStoreAdapter.with_env_storage()

        # Should not raise - file_read doesn't need credentials
        creds.validate_for_tools(["file_read"])

    def test_validate_for_tools_passes_for_empty_list(self):
        """validate_for_tools() succeeds for empty tool list."""
        creds = CredentialStoreAdapter.with_env_storage()

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

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)

        # Should not raise because credential is optional
        creds.validate_for_tools(["optional_tool"])


class TestCredentialStoreAdapterForTesting:
    """Tests for test factory method."""

    def test_for_testing_uses_overrides(self):
        """for_testing() uses provided override values."""
        creds = CredentialStoreAdapter.for_testing({"brave_search": "mock-key"})

        assert creds.get("brave_search") == "mock-key"

    def test_for_testing_ignores_env(self, monkeypatch):
        """for_testing() ignores actual environment variables."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "real-key")

        creds = CredentialStoreAdapter.for_testing({"brave_search": "mock-key"})

        assert creds.get("brave_search") == "mock-key"

    def test_for_testing_validation_passes_with_overrides(self):
        """for_testing() credentials pass validation."""
        creds = CredentialStoreAdapter.for_testing({"brave_search": "mock-key"})

        # Should not raise
        creds.validate_for_tools(["web_search"])

    def test_for_testing_validation_fails_without_override(self, monkeypatch):
        """for_testing() without override still fails validation."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.for_testing({})  # No overrides

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

        creds = CredentialStoreAdapter.for_testing(
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
        assert spec.required is False
        assert spec.startup_required is False
        assert "anthropic.com" in spec.help_url


class TestNodeTypeValidation:
    """Tests for node type credential validation."""

    def test_get_missing_for_node_types_returns_missing(self, monkeypatch):
        """get_missing_for_node_types() returns missing credentials."""
        monkeypatch.delenv("REQUIRED_KEY", raising=False)

        custom_specs = {
            "required_cred": CredentialSpec(
                env_var="REQUIRED_KEY",
                node_types=["required_node"],
                required=True,
            )
        }

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)
        missing = creds.get_missing_for_node_types(["required_node"])

        assert len(missing) == 1
        cred_name, spec = missing[0]
        assert cred_name == "required_cred"
        assert spec.env_var == "REQUIRED_KEY"

    def test_get_missing_for_node_types_returns_empty_when_present(self, monkeypatch):
        """get_missing_for_node_types() returns empty when credentials present."""
        monkeypatch.setenv("REQUIRED_KEY", "test-key")

        custom_specs = {
            "required_cred": CredentialSpec(
                env_var="REQUIRED_KEY",
                node_types=["required_node"],
                required=True,
            )
        }

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)
        missing = creds.get_missing_for_node_types(["required_node"])

        assert missing == []

    def test_get_missing_for_node_types_ignores_unknown_types(self, monkeypatch):
        """get_missing_for_node_types() ignores node types without credentials."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()
        missing = creds.get_missing_for_node_types(["unknown_type", "another_type"])

        assert missing == []

    def test_validate_for_node_types_raises_for_missing(self, monkeypatch):
        """validate_for_node_types() raises CredentialError when missing."""
        monkeypatch.delenv("REQUIRED_KEY", raising=False)

        custom_specs = {
            "required_cred": CredentialSpec(
                env_var="REQUIRED_KEY",
                node_types=["required_node"],
                required=True,
            )
        }

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_for_node_types(["required_node"])

        error_msg = str(exc_info.value)
        assert "REQUIRED_KEY" in error_msg
        assert "required_node" in error_msg

    def test_validate_for_node_types_passes_when_present(self, monkeypatch):
        """validate_for_node_types() passes when credentials present."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()

        # Should not raise
        creds.validate_for_node_types(["llm_generate", "llm_tool_use"])


class TestStartupValidation:
    """Tests for startup credential validation."""

    def test_validate_startup_raises_for_missing(self, monkeypatch):
        """validate_startup() raises CredentialError when startup creds missing."""
        monkeypatch.delenv("STARTUP_KEY", raising=False)

        custom_specs = {
            "startup_cred": CredentialSpec(
                env_var="STARTUP_KEY",
                startup_required=True,
                required=True,
            )
        }

        creds = CredentialStoreAdapter.with_env_storage(specs=custom_specs)

        with pytest.raises(CredentialError) as exc_info:
            creds.validate_startup()

        error_msg = str(exc_info.value)
        assert "STARTUP_KEY" in error_msg
        assert "Server startup failed" in error_msg

    def test_validate_startup_passes_when_present(self, monkeypatch):
        """validate_startup() passes when all startup creds are set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        creds = CredentialStoreAdapter.with_env_storage()

        # Should not raise
        creds.validate_startup()

    def test_validate_startup_ignores_non_startup_creds(self, monkeypatch):
        """validate_startup() ignores credentials without startup_required=True."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        creds = CredentialStoreAdapter.with_env_storage()

        # Should not raise - BRAVE_SEARCH_API_KEY is not startup_required
        creds.validate_startup()

    def test_validate_startup_with_test_overrides(self):
        """validate_startup() works with for_testing() overrides."""
        creds = CredentialStoreAdapter.for_testing({"anthropic": "test-key"})

        # Should not raise
        creds.validate_startup()


class TestSpecCompleteness:
    """Tests that all credential specs have required fields populated."""

    def test_direct_api_key_specs_have_instructions(self):
        """All specs with direct_api_key_supported=True have non-empty api_key_instructions."""
        for name, spec in CREDENTIAL_SPECS.items():
            if spec.direct_api_key_supported:
                assert spec.api_key_instructions.strip(), (
                    f"Credential '{name}' has direct_api_key_supported=True "
                    f"but empty api_key_instructions"
                )

    def test_all_specs_have_credential_id(self):
        """All credential specs have a non-empty credential_id."""
        for name, spec in CREDENTIAL_SPECS.items():
            assert spec.credential_id, f"Credential '{name}' is missing credential_id"

    def test_google_search_and_cse_share_credential_group(self):
        """google_search and google_cse share the same credential_group."""
        google_search = CREDENTIAL_SPECS["google_search"]
        google_cse = CREDENTIAL_SPECS["google_cse"]

        assert google_search.credential_group == "google_custom_search"
        assert google_cse.credential_group == "google_custom_search"
        assert google_search.credential_group == google_cse.credential_group

    def test_credential_group_default_empty(self):
        """Specs without a group have empty credential_group."""
        for name, spec in CREDENTIAL_SPECS.items():
            if name not in ("google_search", "google_cse"):
                assert spec.credential_group == "", (
                    f"Credential '{name}' has unexpected credential_group='{spec.credential_group}'"
                )


class TestCredentialStoreAdapterAdenSync:
    """Tests for Aden sync branch in CredentialStoreAdapter.default()."""

    def _patch_encrypted_storage(self, tmp_path):
        """Patch EncryptedFileStorage to use a temp directory."""
        from framework.credentials.storage import EncryptedFileStorage

        original_init = EncryptedFileStorage.__init__

        def patched_init(self_inner, base_path=None, **kwargs):
            original_init(self_inner, base_path=str(tmp_path / "creds"), **kwargs)

        return patch.object(EncryptedFileStorage, "__init__", patched_init)

    def test_default_with_aden_key_creates_aden_store(self, monkeypatch, tmp_path):
        """When ADEN_API_KEY is set, default() wires up AdenSyncProvider."""
        monkeypatch.setenv("ADEN_API_KEY", "test-aden-key")
        monkeypatch.setenv("ADEN_API_URL", "https://test.adenhq.com")

        mock_client = MagicMock()
        mock_client.list_integrations.return_value = []

        with (
            self._patch_encrypted_storage(tmp_path),
            patch(
                "framework.credentials.aden.AdenCredentialClient",
                return_value=mock_client,
            ),
            patch(
                "framework.credentials.aden.AdenClientConfig",
            ),
        ):
            adapter = CredentialStoreAdapter.default()

        # Verify AdenSyncProvider is registered
        provider = adapter.store.get_provider("aden_sync")
        assert provider is not None

    def test_default_without_aden_key_uses_env_fallback(self, monkeypatch, tmp_path):
        """When ADEN_API_KEY is not set, default() uses env-only storage."""
        monkeypatch.delenv("ADEN_API_KEY", raising=False)
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave-key")

        with self._patch_encrypted_storage(tmp_path):
            adapter = CredentialStoreAdapter.default()

        # No Aden provider should be registered
        assert adapter.store.get_provider("aden_sync") is None
        # Env vars still work
        assert adapter.get("brave_search") == "test-brave-key"

    def test_default_aden_non_aden_cred_falls_through_to_env(self, monkeypatch, tmp_path):
        """Non-Aden credentials (e.g. brave_search) resolve from env vars even with Aden."""
        monkeypatch.setenv("ADEN_API_KEY", "test-aden-key")
        monkeypatch.setenv("ADEN_API_URL", "https://test.adenhq.com")
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-from-env")

        mock_client = MagicMock()
        mock_client.list_integrations.return_value = []
        # Aden returns None for brave_search (404 → None)
        mock_client.get_credential.return_value = None

        with (
            self._patch_encrypted_storage(tmp_path),
            patch(
                "framework.credentials.aden.AdenCredentialClient",
                return_value=mock_client,
            ),
            patch(
                "framework.credentials.aden.AdenClientConfig",
            ),
        ):
            adapter = CredentialStoreAdapter.default()

        assert adapter.get("brave_search") == "brave-from-env"

    def test_default_aden_sync_failure_falls_back_gracefully(self, monkeypatch, tmp_path):
        """If Aden initial sync fails, adapter is still created and env vars work."""
        monkeypatch.setenv("ADEN_API_KEY", "test-aden-key")
        monkeypatch.setenv("ADEN_API_URL", "https://test.adenhq.com")
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-fallback")

        mock_client = MagicMock()
        mock_client.list_integrations.side_effect = Exception("Connection refused")
        mock_client.get_credential.return_value = None

        with (
            self._patch_encrypted_storage(tmp_path),
            patch(
                "framework.credentials.aden.AdenCredentialClient",
                return_value=mock_client,
            ),
            patch(
                "framework.credentials.aden.AdenClientConfig",
            ),
        ):
            adapter = CredentialStoreAdapter.default()

        # Adapter was created despite sync failure
        assert adapter is not None
        assert adapter.get("brave_search") == "brave-fallback"

    def test_default_aden_import_error_falls_back(self, monkeypatch, tmp_path):
        """If Aden imports fail (e.g. missing httpx), fall back to default storage."""
        monkeypatch.setenv("ADEN_API_KEY", "test-aden-key")
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-fallback")

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "framework.credentials.aden":
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with (
            self._patch_encrypted_storage(tmp_path),
            patch.object(builtins, "__import__", side_effect=mock_import),
        ):
            adapter = CredentialStoreAdapter.default()

        # Fell back to default — env vars still work, no Aden provider
        assert adapter.store.get_provider("aden_sync") is None
        assert adapter.get("brave_search") == "brave-fallback"
