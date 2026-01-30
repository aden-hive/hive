"""
OAuth2 support for the credential store.

This module provides OAuth2 credential management with:
- Token types and configuration (OAuth2Token, OAuth2Config)
- Generic OAuth2 provider (BaseOAuth2Provider)
- Token lifecycle management (TokenLifecycleManager)

Quick Start:
    from core.framework.credentials import CredentialStore
    from core.framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config

    # Configure OAuth2 provider
    provider = BaseOAuth2Provider(OAuth2Config(
        token_url="https://oauth2.example.com/token",
        client_id="your-client-id",
        client_secret="your-client-secret",
        default_scopes=["read", "write"],
    ))

    # Create store with OAuth2 provider
    store = CredentialStore.with_encrypted_storage(
        "/var/hive/credentials",
        providers=[provider]
    )

    # Get token using client credentials
    token = provider.client_credentials_grant()

    # Save to store
    from core.framework.credentials import CredentialObject, CredentialKey, CredentialType
    from pydantic import SecretStr

    store.save_credential(CredentialObject(
        id="my_api",
        credential_type=CredentialType.OAUTH2,
        keys={
            "access_token": CredentialKey(
                name="access_token",
                value=SecretStr(token.access_token),
                expires_at=token.expires_at,
            ),
            "refresh_token": CredentialKey(
                name="refresh_token",
                value=SecretStr(token.refresh_token),
            ) if token.refresh_token else None,
        },
        provider_id="oauth2",
        auto_refresh=True,
    ))

For advanced lifecycle management:
    from core.framework.credentials.oauth2 import TokenLifecycleManager

    manager = TokenLifecycleManager(
        provider=provider,
        credential_id="my_api",
        store=store,
    )

    # Get valid token (auto-refreshes if needed)
    token = manager.sync_get_valid_token()
    headers = manager.get_request_headers()
"""

from .base_provider import BaseOAuth2Provider
from .lifecycle import TokenLifecycleManager, TokenRefreshResult
from .provider import (
    OAuth2Config,
    OAuth2Error,
    OAuth2Token,
    RefreshTokenInvalidError,
    TokenExpiredError,
    TokenPlacement,
)

__all__ = [
    # Types
    "OAuth2Token",
    "OAuth2Config",
    "TokenPlacement",
    # Provider
    "BaseOAuth2Provider",
    # Lifecycle
    "TokenLifecycleManager",
    "TokenRefreshResult",
    # Errors
    "OAuth2Error",
    "TokenExpiredError",
    "RefreshTokenInvalidError",
]
