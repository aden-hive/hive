"""
Comprehensive tests for the credential store module.

Tests cover:
- Core models (CredentialObject, CredentialKey, CredentialUsageSpec)
- Template resolution
- Storage backends (InMemoryStorage, EnvVarStorage, EncryptedFileStorage)
- Providers (StaticProvider, BearerTokenProvider)
- Main CredentialStore
- OAuth2 module
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from core.framework.credentials import (
    BearerTokenProvider,
    CompositeStorage,
    CredentialError,
    CredentialKey,
    CredentialKeyNotFoundError,
    CredentialNotFoundError,
    CredentialObject,
    CredentialProvider,
    CredentialRefreshError,
    CredentialStorage,
    CredentialStore,
    CredentialType,
    CredentialUsageSpec,
    EncryptedFileStorage,
    EnvVarStorage,
    InMemoryStorage,
    StaticProvider,
    TemplateResolver,
)


class TestCredentialKey:
    """Tests for CredentialKey model."""

    def test_create_basic_key(self):
        """Test creating a basic credential key."""
        key = CredentialKey(name="api_key", value=SecretStr("test-value"))
        assert key.name == "api_key"
        assert key.get_secret_value() == "test-value"
        assert key.expires_at is None
        assert not key.is_expired

    def test_key_with_expiration(self):
        """Test key with expiration time."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        key = CredentialKey(name="token", value=SecretStr("xxx"), expires_at=future)
        assert not key.is_expired

    def test_expired_key(self):
        """Test that expired key is detected."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        key = CredentialKey(name="token", value=SecretStr("xxx"), expires_at=past)
        assert key.is_expired

    def test_key_with_metadata(self):
        """Test key with metadata."""
        key = CredentialKey(
            name="token",
            value=SecretStr("xxx"),
            metadata={"client_id": "abc", "scope": "read"},
        )
        assert key.metadata["client_id"] == "abc"


class TestCredentialObject:
    """Tests for CredentialObject model."""

    def test_create_simple_credential(self):
        """Test creating a simple API key credential."""
        cred = CredentialObject(
            id="brave_search",
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("test-key"))},
        )
        assert cred.id == "brave_search"
        assert cred.credential_type == CredentialType.API_KEY
        assert cred.get_key("api_key") == "test-key"

    def test_create_multi_key_credential(self):
        """Test creating a credential with multiple keys."""
        cred = CredentialObject(
            id="github_oauth",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(name="access_token", value=SecretStr("ghp_xxx")),
                "refresh_token": CredentialKey(name="refresh_token", value=SecretStr("ghr_xxx")),
            },
        )
        assert cred.get_key("access_token") == "ghp_xxx"
        assert cred.get_key("refresh_token") == "ghr_xxx"
        assert cred.get_key("nonexistent") is None

    def test_set_key(self):
        """Test setting a key on a credential."""
        cred = CredentialObject(id="test", keys={})
        cred.set_key("new_key", "new_value")
        assert cred.get_key("new_key") == "new_value"

    def test_set_key_with_expiration(self):
        """Test setting a key with expiration."""
        cred = CredentialObject(id="test", keys={})
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        cred.set_key("token", "xxx", expires_at=expires)
        assert cred.keys["token"].expires_at == expires

    def test_needs_refresh(self):
        """Test needs_refresh property."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        cred = CredentialObject(
            id="test",
            keys={"token": CredentialKey(name="token", value=SecretStr("xxx"), expires_at=past)},
        )
        assert cred.needs_refresh

    def test_get_default_key(self):
        """Test get_default_key returns appropriate default."""
        # With api_key
        cred = CredentialObject(
            id="test",
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("key-value"))},
        )
        assert cred.get_default_key() == "key-value"

        # With access_token
        cred2 = CredentialObject(
            id="test",
            keys={"access_token": CredentialKey(name="access_token", value=SecretStr("token-value"))},
        )
        assert cred2.get_default_key() == "token-value"

    def test_record_usage(self):
        """Test recording credential usage."""
        cred = CredentialObject(id="test", keys={})
        assert cred.use_count == 0
        assert cred.last_used is None

        cred.record_usage()
        assert cred.use_count == 1
        assert cred.last_used is not None


class TestCredentialUsageSpec:
    """Tests for CredentialUsageSpec model."""

    def test_create_usage_spec(self):
        """Test creating a usage spec."""
        spec = CredentialUsageSpec(
            credential_id="brave_search",
            required_keys=["api_key"],
            headers={"X-Subscription-Token": "{{api_key}}"},
        )
        assert spec.credential_id == "brave_search"
        assert "api_key" in spec.required_keys
        assert "{{api_key}}" in spec.headers.values()


class TestInMemoryStorage:
    """Tests for InMemoryStorage."""

    def test_save_and_load(self):
        """Test saving and loading a credential."""
        storage = InMemoryStorage()
        cred = CredentialObject(
            id="test",
            keys={"key": CredentialKey(name="key", value=SecretStr("value"))},
        )

        storage.save(cred)
        loaded = storage.load("test")

        assert loaded is not None
        assert loaded.id == "test"
        assert loaded.get_key("key") == "value"

    def test_load_nonexistent(self):
        """Test loading a nonexistent credential."""
        storage = InMemoryStorage()
        assert storage.load("nonexistent") is None

    def test_delete(self):
        """Test deleting a credential."""
        storage = InMemoryStorage()
        cred = CredentialObject(id="test", keys={})
        storage.save(cred)

        assert storage.delete("test")
        assert storage.load("test") is None
        assert not storage.delete("test")

    def test_list_all(self):
        """Test listing all credentials."""
        storage = InMemoryStorage()
        storage.save(CredentialObject(id="a", keys={}))
        storage.save(CredentialObject(id="b", keys={}))

        ids = storage.list_all()
        assert "a" in ids
        assert "b" in ids

    def test_exists(self):
        """Test checking if credential exists."""
        storage = InMemoryStorage()
        storage.save(CredentialObject(id="test", keys={}))

        assert storage.exists("test")
        assert not storage.exists("nonexistent")

    def test_clear(self):
        """Test clearing all credentials."""
        storage = InMemoryStorage()
        storage.save(CredentialObject(id="test", keys={}))
        storage.clear()

        assert storage.list_all() == []


class TestEnvVarStorage:
    """Tests for EnvVarStorage."""

    def test_load_from_env(self):
        """Test loading credential from environment variable."""
        with patch.dict(os.environ, {"TEST_API_KEY": "test-value"}):
            storage = EnvVarStorage(env_mapping={"test": "TEST_API_KEY"})
            cred = storage.load("test")

            assert cred is not None
            assert cred.get_key("api_key") == "test-value"

    def test_load_nonexistent(self):
        """Test loading when env var is not set."""
        storage = EnvVarStorage(env_mapping={"test": "NONEXISTENT_VAR"})
        assert storage.load("test") is None

    def test_default_env_var_pattern(self):
        """Test default env var naming pattern."""
        with patch.dict(os.environ, {"MY_SERVICE_API_KEY": "value"}):
            storage = EnvVarStorage()
            cred = storage.load("my_service")

            assert cred is not None
            assert cred.get_key("api_key") == "value"

    def test_save_raises(self):
        """Test that save raises NotImplementedError."""
        storage = EnvVarStorage()
        with pytest.raises(NotImplementedError):
            storage.save(CredentialObject(id="test", keys={}))

    def test_delete_raises(self):
        """Test that delete raises NotImplementedError."""
        storage = EnvVarStorage()
        with pytest.raises(NotImplementedError):
            storage.delete("test")


class TestEncryptedFileStorage:
    """Tests for EncryptedFileStorage."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage(self, temp_dir):
        """Create EncryptedFileStorage for tests."""
        return EncryptedFileStorage(temp_dir)

    def test_save_and_load(self, storage):
        """Test saving and loading encrypted credential."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("secret-value"))},
        )

        storage.save(cred)
        loaded = storage.load("test")

        assert loaded is not None
        assert loaded.id == "test"
        assert loaded.get_key("api_key") == "secret-value"

    def test_encryption_key_from_env(self, temp_dir):
        """Test using encryption key from environment variable."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"HIVE_CREDENTIAL_KEY": key}):
            storage = EncryptedFileStorage(temp_dir)
            cred = CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("v"))})
            storage.save(cred)

            # Create new storage instance with same key
            storage2 = EncryptedFileStorage(temp_dir)
            loaded = storage2.load("test")
            assert loaded is not None
            assert loaded.get_key("k") == "v"

    def test_list_all(self, storage):
        """Test listing all credentials."""
        storage.save(CredentialObject(id="cred1", keys={}))
        storage.save(CredentialObject(id="cred2", keys={}))

        ids = storage.list_all()
        assert "cred1" in ids
        assert "cred2" in ids

    def test_delete(self, storage):
        """Test deleting a credential."""
        storage.save(CredentialObject(id="test", keys={}))
        assert storage.delete("test")
        assert storage.load("test") is None


class TestCompositeStorage:
    """Tests for CompositeStorage."""

    def test_read_from_primary(self):
        """Test reading from primary storage."""
        primary = InMemoryStorage()
        primary.save(CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("primary"))}))

        fallback = InMemoryStorage()
        fallback.save(CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("fallback"))}))

        storage = CompositeStorage(primary, [fallback])
        cred = storage.load("test")

        # Should get from primary
        assert cred.get_key("k") == "primary"

    def test_fallback_when_not_in_primary(self):
        """Test fallback when credential not in primary."""
        primary = InMemoryStorage()
        fallback = InMemoryStorage()
        fallback.save(CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("fallback"))}))

        storage = CompositeStorage(primary, [fallback])
        cred = storage.load("test")

        assert cred.get_key("k") == "fallback"

    def test_write_to_primary_only(self):
        """Test that writes go to primary only."""
        primary = InMemoryStorage()
        fallback = InMemoryStorage()

        storage = CompositeStorage(primary, [fallback])
        storage.save(CredentialObject(id="test", keys={}))

        assert primary.exists("test")
        assert not fallback.exists("test")


class TestStaticProvider:
    """Tests for StaticProvider."""

    def test_provider_id(self):
        """Test provider ID."""
        provider = StaticProvider()
        assert provider.provider_id == "static"

    def test_supported_types(self):
        """Test supported credential types."""
        provider = StaticProvider()
        assert CredentialType.API_KEY in provider.supported_types
        assert CredentialType.CUSTOM in provider.supported_types

    def test_refresh_returns_unchanged(self):
        """Test that refresh returns credential unchanged."""
        provider = StaticProvider()
        cred = CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("v"))})

        refreshed = provider.refresh(cred)
        assert refreshed.get_key("k") == "v"

    def test_validate_with_keys(self):
        """Test validation with keys present."""
        provider = StaticProvider()
        cred = CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("v"))})

        assert provider.validate(cred)

    def test_validate_without_keys(self):
        """Test validation without keys."""
        provider = StaticProvider()
        cred = CredentialObject(id="test", keys={})

        assert not provider.validate(cred)

    def test_should_refresh(self):
        """Test that static provider never needs refresh."""
        provider = StaticProvider()
        cred = CredentialObject(id="test", keys={})

        assert not provider.should_refresh(cred)


class TestTemplateResolver:
    """Tests for TemplateResolver."""

    @pytest.fixture
    def store(self):
        """Create a test store with credentials."""
        return CredentialStore.for_testing(
            {
                "brave_search": {"api_key": "test-brave-key"},
                "github_oauth": {"access_token": "ghp_xxx", "refresh_token": "ghr_xxx"},
            }
        )

    @pytest.fixture
    def resolver(self, store):
        """Create a resolver with the test store."""
        return TemplateResolver(store)

    def test_resolve_simple(self, resolver):
        """Test resolving a simple template."""
        result = resolver.resolve("Bearer {{github_oauth.access_token}}")
        assert result == "Bearer ghp_xxx"

    def test_resolve_multiple(self, resolver):
        """Test resolving multiple templates."""
        result = resolver.resolve("{{github_oauth.access_token}} and {{brave_search.api_key}}")
        assert "ghp_xxx" in result
        assert "test-brave-key" in result

    def test_resolve_default_key(self, resolver):
        """Test resolving credential without key specified."""
        result = resolver.resolve("Key: {{brave_search}}")
        assert "test-brave-key" in result

    def test_resolve_headers(self, resolver):
        """Test resolving headers dict."""
        headers = resolver.resolve_headers(
            {
                "Authorization": "Bearer {{github_oauth.access_token}}",
                "X-API-Key": "{{brave_search.api_key}}",
            }
        )
        assert headers["Authorization"] == "Bearer ghp_xxx"
        assert headers["X-API-Key"] == "test-brave-key"

    def test_resolve_missing_credential(self, resolver):
        """Test error on missing credential."""
        with pytest.raises(CredentialNotFoundError):
            resolver.resolve("{{nonexistent.key}}")

    def test_resolve_missing_key(self, resolver):
        """Test error on missing key."""
        with pytest.raises(CredentialKeyNotFoundError):
            resolver.resolve("{{github_oauth.nonexistent}}")

    def test_has_templates(self, resolver):
        """Test detecting templates in text."""
        assert resolver.has_templates("{{cred.key}}")
        assert resolver.has_templates("Bearer {{token}}")
        assert not resolver.has_templates("no templates here")

    def test_extract_references(self, resolver):
        """Test extracting credential references."""
        refs = resolver.extract_references("{{github.token}} and {{brave.key}}")
        assert ("github", "token") in refs
        assert ("brave", "key") in refs


class TestCredentialStore:
    """Tests for CredentialStore."""

    def test_for_testing_factory(self):
        """Test creating store for testing."""
        store = CredentialStore.for_testing({"test": {"api_key": "value"}})

        assert store.get("test") == "value"
        assert store.get_key("test", "api_key") == "value"

    def test_get_credential(self):
        """Test getting a credential."""
        store = CredentialStore.for_testing({"test": {"key": "value"}})

        cred = store.get_credential("test")
        assert cred is not None
        assert cred.get_key("key") == "value"

    def test_get_nonexistent(self):
        """Test getting nonexistent credential."""
        store = CredentialStore.for_testing({})
        assert store.get_credential("nonexistent") is None
        assert store.get("nonexistent") is None

    def test_save_and_load(self):
        """Test saving and loading a credential."""
        store = CredentialStore.for_testing({})

        cred = CredentialObject(id="new", keys={"k": CredentialKey(name="k", value=SecretStr("v"))})
        store.save_credential(cred)

        loaded = store.get_credential("new")
        assert loaded is not None
        assert loaded.get_key("k") == "v"

    def test_delete_credential(self):
        """Test deleting a credential."""
        store = CredentialStore.for_testing({"test": {"k": "v"}})

        assert store.delete_credential("test")
        assert store.get_credential("test") is None

    def test_list_credentials(self):
        """Test listing all credentials."""
        store = CredentialStore.for_testing({"a": {"k": "v"}, "b": {"k": "v"}})

        ids = store.list_credentials()
        assert "a" in ids
        assert "b" in ids

    def test_is_available(self):
        """Test checking credential availability."""
        store = CredentialStore.for_testing({"test": {"k": "v"}})

        assert store.is_available("test")
        assert not store.is_available("nonexistent")

    def test_resolve_templates(self):
        """Test template resolution through store."""
        store = CredentialStore.for_testing({"test": {"api_key": "value"}})

        result = store.resolve("Key: {{test.api_key}}")
        assert result == "Key: value"

    def test_resolve_headers(self):
        """Test resolving headers through store."""
        store = CredentialStore.for_testing({"test": {"token": "xxx"}})

        headers = store.resolve_headers({"Authorization": "Bearer {{test.token}}"})
        assert headers["Authorization"] == "Bearer xxx"

    def test_register_provider(self):
        """Test registering a provider."""
        store = CredentialStore.for_testing({})
        provider = StaticProvider()

        store.register_provider(provider)
        assert store.get_provider("static") is provider

    def test_register_usage_spec(self):
        """Test registering a usage spec."""
        store = CredentialStore.for_testing({})
        spec = CredentialUsageSpec(
            credential_id="test",
            required_keys=["api_key"],
            headers={"X-Key": "{{api_key}}"},
        )

        store.register_usage(spec)
        assert store.get_usage_spec("test") is spec

    def test_validate_for_usage(self):
        """Test validating credential for usage spec."""
        store = CredentialStore.for_testing({"test": {"api_key": "value"}})
        spec = CredentialUsageSpec(credential_id="test", required_keys=["api_key"])
        store.register_usage(spec)

        errors = store.validate_for_usage("test")
        assert errors == []

    def test_validate_for_usage_missing_key(self):
        """Test validation with missing required key."""
        store = CredentialStore.for_testing({"test": {"other_key": "value"}})
        spec = CredentialUsageSpec(credential_id="test", required_keys=["api_key"])
        store.register_usage(spec)

        errors = store.validate_for_usage("test")
        assert "api_key" in errors[0]

    def test_caching(self):
        """Test that credentials are cached."""
        storage = InMemoryStorage()
        store = CredentialStore(storage=storage, cache_ttl_seconds=60)

        storage.save(CredentialObject(id="test", keys={"k": CredentialKey(name="k", value=SecretStr("v"))}))

        # First load
        cred1 = store.get_credential("test")

        # Delete from storage
        storage.delete("test")

        # Should still get from cache
        cred2 = store.get_credential("test")
        assert cred2 is not None

    def test_clear_cache(self):
        """Test clearing the cache."""
        storage = InMemoryStorage()
        store = CredentialStore(storage=storage)

        storage.save(CredentialObject(id="test", keys={}))
        store.get_credential("test")  # Cache it

        storage.delete("test")
        store.clear_cache()

        # Should not find in cache now
        assert store.get_credential("test") is None


class TestOAuth2Module:
    """Tests for OAuth2 module."""

    def test_oauth2_token_from_response(self):
        """Test creating OAuth2Token from token response."""
        from core.framework.credentials.oauth2 import OAuth2Token

        response = {
            "access_token": "xxx",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "yyy",
            "scope": "read write",
        }

        token = OAuth2Token.from_token_response(response)
        assert token.access_token == "xxx"
        assert token.token_type == "Bearer"
        assert token.refresh_token == "yyy"
        assert token.scope == "read write"
        assert token.expires_at is not None

    def test_token_is_expired(self):
        """Test token expiration check."""
        from core.framework.credentials.oauth2 import OAuth2Token

        # Not expired
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        token = OAuth2Token(access_token="xxx", expires_at=future)
        assert not token.is_expired

        # Expired
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        expired_token = OAuth2Token(access_token="xxx", expires_at=past)
        assert expired_token.is_expired

    def test_token_can_refresh(self):
        """Test token refresh capability check."""
        from core.framework.credentials.oauth2 import OAuth2Token

        with_refresh = OAuth2Token(access_token="xxx", refresh_token="yyy")
        assert with_refresh.can_refresh

        without_refresh = OAuth2Token(access_token="xxx")
        assert not without_refresh.can_refresh

    def test_oauth2_config_validation(self):
        """Test OAuth2Config validation."""
        from core.framework.credentials.oauth2 import OAuth2Config, TokenPlacement

        # Valid config
        config = OAuth2Config(token_url="https://example.com/token", client_id="id", client_secret="secret")
        assert config.token_url == "https://example.com/token"

        # Missing token_url
        with pytest.raises(ValueError):
            OAuth2Config(token_url="")

        # HEADER_CUSTOM without custom_header_name
        with pytest.raises(ValueError):
            OAuth2Config(
                token_url="https://example.com/token",
                token_placement=TokenPlacement.HEADER_CUSTOM,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
