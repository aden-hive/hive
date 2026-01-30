from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from framework.credentials.models import (
    CredentialObject,
    CredentialType,
    CredentialKey,
    CredentialRefreshError,
)
from framework.credentials.provider import StaticProvider, BearerTokenProvider


class TestStaticProvider:
    @pytest.fixture
    def provider(self):
        return StaticProvider()

    def test_provider_metadata(self, provider):
        """Test provider identification"""
        assert provider.provider_id == "static"
        assert CredentialType.API_KEY in provider.supported_types
        assert CredentialType.BASIC_AUTH in provider.supported_types

    def test_validate_valid_credential(self, provider):
        """Test validation with a valid API key"""
        credential = CredentialObject(
            id="test_api",
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("sk-12345"))},
        )
        assert provider.validate(credential) is True

    def test_validate_empty_credential(self, provider):
        """Test validation fails with no keys"""
        credential = CredentialObject(
            id="test_empty", credential_type=CredentialType.API_KEY, keys={}
        )
        assert provider.validate(credential) is False

    def test_validate_empty_value(self, provider):
        """Test validation fails with empty secret value"""
        credential = CredentialObject(
            id="test_empty_val",
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr(""))},
        )
        assert provider.validate(credential) is False

    def test_refresh_no_op(self, provider):
        """Test that refresh returns credential unchanged"""
        credential = CredentialObject(
            id="test_refresh",
            credential_type=CredentialType.API_KEY,
            keys={"k": CredentialKey(name="k", value=SecretStr("v"))},
        )
        # Should return same object
        refreshed = provider.refresh(credential)
        assert refreshed is credential
        assert refreshed.get_key("k") == "v"


class TestBearerTokenProvider:
    @pytest.fixture
    def provider(self):
        return BearerTokenProvider()

    def test_provider_metadata(self, provider):
        """Test provider identification"""
        assert provider.provider_id == "bearer_token"
        assert CredentialType.BEARER_TOKEN in provider.supported_types

    def test_validate_valid_token(self, provider):
        """Test validation with valid unexpired token"""
        future = datetime.now(UTC) + timedelta(hours=1)
        credential = CredentialObject(
            id="test_token",
            credential_type=CredentialType.BEARER_TOKEN,
            keys={
                "token": CredentialKey(name="token", value=SecretStr("eyJ..."), expires_at=future)
            },
        )
        assert provider.validate(credential) is True

    def test_validate_expired_token(self, provider):
        """Test validation fails with expired token"""
        past = datetime.now(UTC) - timedelta(hours=1)
        credential = CredentialObject(
            id="test_expired",
            credential_type=CredentialType.BEARER_TOKEN,
            keys={"token": CredentialKey(name="token", value=SecretStr("eyJ..."), expires_at=past)},
        )
        assert provider.validate(credential) is False

    def test_should_refresh_near_expiry(self, provider):
        """Test should_refresh returns True when near expiration"""
        # Expires in 2 minutes (less than 5 min buffer)
        near_future = datetime.now(UTC) + timedelta(minutes=2)
        credential = CredentialObject(
            id="test_expiring",
            credential_type=CredentialType.BEARER_TOKEN,
            keys={
                "token": CredentialKey(name="token", value=SecretStr("val"), expires_at=near_future)
            },
        )
        assert provider.should_refresh(credential) is True

    def test_refresh_raises_error(self, provider):
        """Test that refresh raises error as expected"""
        credential = CredentialObject(
            id="test_refresh", credential_type=CredentialType.BEARER_TOKEN
        )
        with pytest.raises(CredentialRefreshError):
            provider.refresh(credential)
