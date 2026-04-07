"""
Tests for Aden credential sync components.

Tests cover:
- AdenCredentialClient: HTTP client for Aden API
- AdenSyncProvider: Provider that syncs with Aden
- AdenCachedStorage: Storage with local cache + Aden fallback
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from framework.credentials import (
    CredentialKey,
    CredentialObject,
    CredentialStore,
    CredentialType,
    InMemoryStorage,
)
from framework.credentials.aden import (
    AdenCachedStorage,
    AdenClientConfig,
    AdenClientError,
    AdenCredentialClient,
    AdenCredentialResponse,
    AdenIntegrationInfo,
    AdenRefreshError,
    AdenSyncProvider,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def aden_config():
    """Create a test Aden client config."""
    return AdenClientConfig(
        base_url="https://api.test-aden.com",
        api_key="test-api-key",
        tenant_id="test-tenant",
        timeout=5.0,
        retry_attempts=2,
        retry_delay=0.1,
    )


@pytest.fixture
def mock_client(aden_config):
    """Create a mock Aden client."""
    client = Mock(spec=AdenCredentialClient)
    client.config = aden_config
    return client


@pytest.fixture
def aden_response():
    """Create a sample Aden credential response."""
    return AdenCredentialResponse(
        integration_id="aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1",
        access_token="test-access-token",
        token_type="Bearer",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        provider="hubspot",
        alias="My HubSpot",
        email="test@example.com",
        scopes=["crm.objects.contacts.read", "crm.objects.contacts.write"],
        metadata={"portal_id": "12345"},
    )


@pytest.fixture
def provider(mock_client):
    """Create an AdenSyncProvider with mock client."""
    return AdenSyncProvider(
        client=mock_client,
        provider_id="test_aden",
        refresh_buffer_minutes=5,
        report_usage=False,
    )


@pytest.fixture
def local_storage():
    """Create an in-memory storage for testing."""
    return InMemoryStorage()


@pytest.fixture
def cached_storage(local_storage, provider):
    """Create an AdenCachedStorage for testing."""
    return AdenCachedStorage(
        local_storage=local_storage,
        aden_provider=provider,
        cache_ttl_seconds=60,
        prefer_local=True,
    )


# =============================================================================
# AdenCredentialResponse Tests
# =============================================================================


class TestAdenCredentialResponse:
    """Tests for AdenCredentialResponse dataclass."""

    def test_from_dict_basic(self):
        """Test creating response from dict (real get-token format)."""
        data = {
            "access_token": "ghp_xxxxx",
            "token_type": "Bearer",
            "provider": "github",
            "alias": "Work",
        }

        response = AdenCredentialResponse.from_dict(data, integration_id="Z2l0aHViOldvcms6MTIzNDU")

        assert response.integration_id == "Z2l0aHViOldvcms6MTIzNDU"
        assert response.access_token == "ghp_xxxxx"
        assert response.provider == "github"
        assert response.integration_type == "github"  # backward compat property
        assert response.token_type == "Bearer"
        assert response.expires_at is None
        assert response.scopes == []

    def test_from_dict_full(self):
        """Test creating response with all fields."""
        data = {
            "access_token": "token123",
            "token_type": "Bearer",
            "expires_at": "2026-01-28T15:30:00Z",
            "provider": "hubspot",
            "alias": "My HubSpot",
            "email": "test@example.com",
            "scopes": ["read", "write"],
            "metadata": {"key": "value"},
        }

        response = AdenCredentialResponse.from_dict(data, integration_id="aHVic3BvdDp0ZXN0")

        assert response.integration_id == "aHVic3BvdDp0ZXN0"
        assert response.access_token == "token123"
        assert response.provider == "hubspot"
        assert response.alias == "My HubSpot"
        assert response.email == "test@example.com"
        assert response.expires_at is not None
        assert response.scopes == ["read", "write"]
        assert response.metadata == {"key": "value"}


class TestAdenIntegrationInfo:
    """Tests for AdenIntegrationInfo dataclass."""

    def test_from_dict(self):
        """Test creating integration info from real API format."""
        data = {
            "integration_id": "c2xhY2s6V29yayBTbGFjazoxMjM0NQ",
            "provider": "slack",
            "alias": "Work Slack",
            "status": "active",
            "email": "user@example.com",
            "expires_at": "2026-02-20T21:46:04.863Z",
        }

        info = AdenIntegrationInfo.from_dict(data)

        assert info.integration_id == "c2xhY2s6V29yayBTbGFjazoxMjM0NQ"
        assert info.provider == "slack"
        assert info.integration_type == "slack"  # backward compat property
        assert info.alias == "Work Slack"
        assert info.email == "user@example.com"
        assert info.status == "active"
        assert info.expires_at is not None

    def test_from_dict_minimal(self):
        """Test creating integration info with minimal fields."""
        data = {
            "integration_id": "Z29vZ2xlOlRpbW90aHk6MTYwNjc",
            "provider": "google",
            "alias": "Timothy",
            "status": "requires_reauth",
        }

        info = AdenIntegrationInfo.from_dict(data)

        assert info.integration_id == "Z29vZ2xlOlRpbW90aHk6MTYwNjc"
        assert info.provider == "google"
        assert info.alias == "Timothy"
        assert info.status == "requires_reauth"
        assert info.email == ""
        assert info.expires_at is None


# =============================================================================
# AdenSyncProvider Tests
# =============================================================================


class TestAdenSyncProvider:
    """Tests for AdenSyncProvider."""

    def test_provider_id(self, provider):
        """Test provider ID."""
        assert provider.provider_id == "test_aden"

    def test_supported_types(self, provider):
        """Test supported credential types."""
        assert CredentialType.OAUTH2 in provider.supported_types
        assert CredentialType.BEARER_TOKEN in provider.supported_types

    def test_can_handle_oauth2(self, provider):
        """Test can_handle returns True for OAUTH2 credentials with matching provider_id."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={},
            provider_id="test_aden",
        )

        assert provider.can_handle(cred) is True

    def test_can_handle_aden_managed(self, provider):
        """Test can_handle returns True for Aden-managed credentials."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "_aden_managed": CredentialKey(
                    name="_aden_managed",
                    value=SecretStr("true"),
                )
            },
        )

        assert provider.can_handle(cred) is True

    def test_can_handle_wrong_type(self, provider):
        """Test can_handle returns False for unsupported types."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.API_KEY,
            keys={},
        )

        assert provider.can_handle(cred) is False

    def test_refresh_success(self, provider, mock_client, aden_response):
        """Test successful credential refresh."""
        hash_id = "aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"
        mock_client.request_refresh.return_value = aden_response

        cred = CredentialObject(
            id=hash_id,
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("old-token"),
                )
            },
            provider_id="test_aden",
        )

        refreshed = provider.refresh(cred)

        assert refreshed.keys["access_token"].value.get_secret_value() == "test-access-token"
        assert refreshed.keys["_aden_managed"].value.get_secret_value() == "true"
        assert refreshed.last_refreshed is not None
        mock_client.request_refresh.assert_called_once_with(hash_id)

    def test_refresh_requires_reauth(self, provider, mock_client):
        """Test refresh that requires re-authorization."""
        mock_client.request_refresh.side_effect = AdenRefreshError(
            "Token revoked",
            requires_reauthorization=True,
            reauthorization_url="https://aden.com/reauth",
        )

        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={},
        )

        from framework.credentials import CredentialRefreshError

        with pytest.raises(CredentialRefreshError) as exc_info:
            provider.refresh(cred)

        assert "re-authorization" in str(exc_info.value).lower()

    def test_refresh_aden_unavailable_cached_valid(self, provider, mock_client):
        """Test refresh falls back to cache when Aden is unavailable and token is valid."""
        mock_client.request_refresh.side_effect = AdenClientError("Connection failed")

        # Token expires in 1 hour - still valid
        future = datetime.now(UTC) + timedelta(hours=1)
        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("cached-token"),
                    expires_at=future,
                )
            },
        )

        # Should return the cached credential instead of failing
        result = provider.refresh(cred)

        assert result.keys["access_token"].value.get_secret_value() == "cached-token"

    def test_should_refresh_expired(self, provider):
        """Test should_refresh returns True for expired token."""
        past = datetime.now(UTC) - timedelta(hours=1)
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                    expires_at=past,
                )
            },
        )

        assert provider.should_refresh(cred) is True

    def test_should_refresh_within_buffer(self, provider):
        """Test should_refresh returns True when within buffer."""
        # Expires in 3 minutes (buffer is 5 minutes)
        soon = datetime.now(UTC) + timedelta(minutes=3)
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                    expires_at=soon,
                )
            },
        )

        assert provider.should_refresh(cred) is True

    def test_should_refresh_still_valid(self, provider):
        """Test should_refresh returns False for valid token."""
        future = datetime.now(UTC) + timedelta(hours=1)
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                    expires_at=future,
                )
            },
        )

        assert provider.should_refresh(cred) is False

    def test_fetch_from_aden(self, provider, mock_client, aden_response):
        """Test fetching credential from Aden."""
        hash_id = "aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"
        mock_client.get_credential.return_value = aden_response

        cred = provider.fetch_from_aden(hash_id)

        assert cred is not None
        assert cred.id == hash_id
        assert cred.keys["access_token"].value.get_secret_value() == "test-access-token"
        assert cred.auto_refresh is True

    def test_fetch_from_aden_not_found(self, provider, mock_client):
        """Test fetch returns None when not found."""
        mock_client.get_credential.return_value = None

        cred = provider.fetch_from_aden("nonexistent")

        assert cred is None

    def test_sync_all(self, provider, mock_client, aden_response):
        """Test syncing all credentials."""
        mock_client.list_integrations.return_value = [
            AdenIntegrationInfo(
                integration_id="aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1",
                provider="hubspot",
                alias="My HubSpot",
                status="active",
            ),
            AdenIntegrationInfo(
                integration_id="Z2l0aHViOnRlc3Q6OTk5",
                provider="github",
                alias="Work GitHub",
                status="requires_reauth",  # Should be skipped
            ),
        ]
        mock_client.get_credential.return_value = aden_response

        store = CredentialStore(storage=InMemoryStorage())
        synced = provider.sync_all(store)

        assert synced == 1  # Only active one was synced
        assert store.get_credential("aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1") is not None

    def test_validate_via_aden(self, provider, mock_client):
        """Test validation via Aden introspection."""
        mock_client.validate_token.return_value = {"valid": True}

        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={},
        )

        assert provider.validate(cred) is True

    def test_validate_fallback_to_local(self, provider, mock_client):
        """Test validation falls back to local check when Aden fails."""
        mock_client.validate_token.side_effect = AdenClientError("Failed")

        future = datetime.now(UTC) + timedelta(hours=1)
        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                    expires_at=future,
                )
            },
        )

        assert provider.validate(cred) is True


# =============================================================================
# AdenCachedStorage Tests
# =============================================================================


class TestAdenCachedStorage:
    """Tests for AdenCachedStorage."""

    def test_save_updates_cache_timestamp(self, cached_storage):
        """Test save updates cache timestamp."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                )
            },
        )

        cached_storage.save(cred)

        assert "test" in cached_storage._cache_timestamps
        assert cached_storage.exists("test")

    def test_load_from_fresh_cache(self, cached_storage, local_storage):
        """Test load returns cached credential when fresh."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("cached-token"),
                )
            },
        )

        # Save to both local storage and update timestamp
        local_storage.save(cred)
        cached_storage._cache_timestamps["test"] = datetime.now(UTC)

        loaded = cached_storage.load("test")

        assert loaded is not None
        assert loaded.keys["access_token"].value.get_secret_value() == "cached-token"

    def test_load_from_aden_when_stale(
        self, cached_storage, local_storage, provider, mock_client, aden_response
    ):
        """Test load fetches from Aden when cache is stale."""
        # Create stale cached credential
        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("stale-token"),
                )
            },
        )
        local_storage.save(cred)

        # Set cache timestamp to be stale (2 minutes ago, TTL is 60 seconds)
        cached_storage._cache_timestamps["hubspot"] = datetime.now(UTC) - timedelta(minutes=2)

        # Mock Aden response
        mock_client.get_credential.return_value = aden_response

        loaded = cached_storage.load("hubspot")

        assert loaded is not None
        assert loaded.keys["access_token"].value.get_secret_value() == "test-access-token"

    def test_load_falls_back_to_stale_when_aden_fails(
        self, cached_storage, local_storage, provider, mock_client
    ):
        """Test load falls back to stale cache when Aden fails."""
        # Create stale cached credential
        cred = CredentialObject(
            id="hubspot",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("stale-token"),
                )
            },
        )
        local_storage.save(cred)
        cached_storage._cache_timestamps["hubspot"] = datetime.now(UTC) - timedelta(minutes=2)

        # Aden fails
        mock_client.get_credential.side_effect = AdenClientError("Connection failed")

        loaded = cached_storage.load("hubspot")

        assert loaded is not None
        assert loaded.keys["access_token"].value.get_secret_value() == "stale-token"

    def test_delete_removes_cache_timestamp(self, cached_storage, local_storage):
        """Test delete removes cache timestamp."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={},
        )
        cached_storage.save(cred)

        assert "test" in cached_storage._cache_timestamps

        cached_storage.delete("test")

        assert "test" not in cached_storage._cache_timestamps
        assert not cached_storage.exists("test")

    def test_invalidate_cache(self, cached_storage, local_storage):
        """Test invalidate_cache removes timestamp."""
        cred = CredentialObject(
            id="test",
            credential_type=CredentialType.OAUTH2,
            keys={},
        )
        cached_storage.save(cred)

        cached_storage.invalidate_cache("test")

        assert "test" not in cached_storage._cache_timestamps
        # Credential still exists in local storage
        assert local_storage.exists("test")

    def test_invalidate_all(self, cached_storage):
        """Test invalidate_all clears all timestamps."""
        for i in range(3):
            cached_storage._cache_timestamps[f"test_{i}"] = datetime.now(UTC)

        cached_storage.invalidate_all()

        assert len(cached_storage._cache_timestamps) == 0

    def test_is_cache_fresh(self, cached_storage):
        """Test _is_cache_fresh logic."""
        # Fresh cache
        cached_storage._cache_timestamps["fresh"] = datetime.now(UTC)
        assert cached_storage._is_cache_fresh("fresh") is True

        # Stale cache
        cached_storage._cache_timestamps["stale"] = datetime.now(UTC) - timedelta(minutes=5)
        assert cached_storage._is_cache_fresh("stale") is False

        # No cache
        assert cached_storage._is_cache_fresh("nonexistent") is False

    def test_get_cache_info(self, cached_storage, local_storage):
        """Test get_cache_info returns status for all credentials."""
        # Add some credentials
        for name in ["fresh", "stale"]:
            cred = CredentialObject(
                id=name,
                credential_type=CredentialType.OAUTH2,
                keys={},
            )
            local_storage.save(cred)

        cached_storage._cache_timestamps["fresh"] = datetime.now(UTC)
        cached_storage._cache_timestamps["stale"] = datetime.now(UTC) - timedelta(minutes=5)

        info = cached_storage.get_cache_info()

        assert "fresh" in info
        assert info["fresh"]["is_fresh"] is True
        assert info["fresh"]["ttl_remaining_seconds"] > 0

        assert "stale" in info
        assert info["stale"]["is_fresh"] is False
        assert info["stale"]["ttl_remaining_seconds"] == 0

    def test_save_indexes_provider(self, cached_storage):
        """Test save builds the provider index from _integration_type key."""
        cred = CredentialObject(
            id="aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token-value"),
                ),
                "_integration_type": CredentialKey(
                    name="_integration_type",
                    value=SecretStr("hubspot"),
                ),
            },
        )

        cached_storage.save(cred)

        assert cached_storage._provider_index["hubspot"] == ["aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"]

    def test_load_by_provider_name(self, cached_storage):
        """Test load resolves provider name to hash-based credential ID."""
        hash_id = "aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"
        cred = CredentialObject(
            id=hash_id,
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("hubspot-token"),
                ),
                "_integration_type": CredentialKey(
                    name="_integration_type",
                    value=SecretStr("hubspot"),
                ),
            },
        )

        # Save builds the index
        cached_storage.save(cred)

        # Load by provider name should resolve to the hash ID
        loaded = cached_storage.load("hubspot")

        assert loaded is not None
        assert loaded.id == hash_id
        assert loaded.keys["access_token"].value.get_secret_value() == "hubspot-token"

    def test_load_by_direct_id_still_works(self, cached_storage):
        """Test load by direct hash ID still works as before."""
        hash_id = "aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"
        cred = CredentialObject(
            id=hash_id,
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("token"),
                ),
                "_integration_type": CredentialKey(
                    name="_integration_type",
                    value=SecretStr("hubspot"),
                ),
            },
        )

        cached_storage.save(cred)

        # Direct ID lookup should still work
        loaded = cached_storage.load(hash_id)

        assert loaded is not None
        assert loaded.id == hash_id

    def test_exists_by_provider_name(self, cached_storage):
        """Test exists resolves provider name to hash-based credential ID."""
        hash_id = "c2xhY2s6dGVzdDo5OTk="
        cred = CredentialObject(
            id=hash_id,
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("slack-token"),
                ),
                "_integration_type": CredentialKey(
                    name="_integration_type",
                    value=SecretStr("slack"),
                ),
            },
        )

        cached_storage.save(cred)

        assert cached_storage.exists("slack") is True
        assert cached_storage.exists(hash_id) is True
        assert cached_storage.exists("nonexistent") is False

    def test_rebuild_provider_index(self, cached_storage, local_storage):
        """Test rebuild_provider_index reconstructs from local storage."""
        # Manually save credentials to local storage (bypassing cached_storage.save)
        for provider_name, hash_id in [("hubspot", "hash_hub"), ("slack", "hash_slack")]:
            cred = CredentialObject(
                id=hash_id,
                credential_type=CredentialType.OAUTH2,
                keys={
                    "_integration_type": CredentialKey(
                        name="_integration_type",
                        value=SecretStr(provider_name),
                    ),
                },
            )
            local_storage.save(cred)

        # Index should be empty (we bypassed save)
        assert len(cached_storage._provider_index) == 0

        # Rebuild
        indexed = cached_storage.rebuild_provider_index()

        assert indexed == 2
        assert cached_storage._provider_index["hubspot"] == ["hash_hub"]
        assert cached_storage._provider_index["slack"] == ["hash_slack"]

    def test_save_without_integration_type_no_index(self, cached_storage):
        """Test save does not index credentials without _integration_type key."""
        cred = CredentialObject(
            id="plain-cred",
            credential_type=CredentialType.API_KEY,
            keys={
                "api_key": CredentialKey(
                    name="api_key",
                    value=SecretStr("key-value"),
                ),
            },
        )

        cached_storage.save(cred)

        assert "plain-cred" not in cached_storage._provider_index
        assert len(cached_storage._provider_index) == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestAdenIntegration:
    """Integration tests for Aden sync components."""

    def test_full_workflow(self, mock_client, aden_response):
        """Test full workflow: sync, get, refresh."""
        hash_id = "aHVic3BvdDp0ZXN0OjEzNjExOjExNTI1"

        # Setup
        mock_client.list_integrations.return_value = [
            AdenIntegrationInfo(
                integration_id=hash_id,
                provider="hubspot",
                alias="My HubSpot",
                status="active",
            ),
        ]
        mock_client.get_credential.return_value = aden_response
        mock_client.request_refresh.return_value = AdenCredentialResponse(
            integration_id=hash_id,
            access_token="refreshed-token",
            provider="hubspot",
            alias="My HubSpot",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            scopes=[],
        )

        provider = AdenSyncProvider(client=mock_client)
        storage = InMemoryStorage()
        store = CredentialStore(
            storage=storage,
            providers=[provider],
            auto_refresh=True,
        )

        # Initial sync
        synced = provider.sync_all(store)
        assert synced == 1

        # Get credential by hash ID
        cred = store.get_credential(hash_id)
        assert cred is not None
        assert cred.keys["access_token"].value.get_secret_value() == "test-access-token"

        # Simulate expiration
        cred.keys["access_token"] = CredentialKey(
            name="access_token",
            value=SecretStr("test-access-token"),
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # Expired
        )
        storage.save(cred)

        # Refresh should be triggered
        refreshed = provider.refresh(cred)
        assert refreshed.keys["access_token"].value.get_secret_value() == "refreshed-token"

    def test_cached_storage_with_store(self, mock_client, aden_response):
        """Test AdenCachedStorage with CredentialStore."""
        mock_client.get_credential.return_value = aden_response

        provider = AdenSyncProvider(client=mock_client)
        local_storage = InMemoryStorage()
        cached_storage = AdenCachedStorage(
            local_storage=local_storage,
            aden_provider=provider,
            cache_ttl_seconds=300,
        )

        # First load fetches from Aden
        cred = cached_storage.load("hubspot")
        assert cred is not None
        mock_client.get_credential.assert_called_once()

        # Second load uses cache
        mock_client.get_credential.reset_mock()
        cred2 = cached_storage.load("hubspot")
        assert cred2 is not None
        mock_client.get_credential.assert_not_called()
