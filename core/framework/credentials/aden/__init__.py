"""
Aden Credential Sync.

Components for synchronizing credentials with the Aden authentication server.

The Aden server handles OAuth2 authorization flows and maintains refresh tokens.
These components fetch and cache access tokens locally while delegating
lifecycle management to Aden.

Components:
- AdenCredentialClient: HTTP client for Aden API
- AdenSyncProvider: CredentialProvider that syncs with Aden
- AdenCachedStorage: Storage with local cache + Aden fallback

Quick Start:
    from core.framework.credentials import CredentialStore
    from core.framework.credentials.storage import EncryptedFileStorage
    from core.framework.credentials.aden import (
        AdenCredentialClient,
        AdenClientConfig,
        AdenSyncProvider,
    )

    # Configure (API key loaded from ADEN_API_KEY env var)
    client = AdenCredentialClient(AdenClientConfig(
        base_url=os.environ["ADEN_API_URL"],
    ))

    provider = AdenSyncProvider(client=client)

    store = CredentialStore(
        storage=EncryptedFileStorage(),
        providers=[provider],
        auto_refresh=True,
    )

    # Initial sync
    provider.sync_all(store)

    # Use normally
    token = store.get_key("hubspot", "access_token")

See docs/aden-credential-sync.md for detailed documentation.
"""

from .client import (
    AdenAuthenticationError,
    AdenClientConfig,
    AdenClientError,
    AdenCredentialClient,
    AdenCredentialResponse,
    AdenIntegrationInfo,
    AdenNotFoundError,
    AdenRateLimitError,
    AdenRefreshError,
)
from .provider import AdenSyncProvider
from .storage import AdenCachedStorage

__all__ = [
    # Client
    "AdenCredentialClient",
    "AdenClientConfig",
    "AdenCredentialResponse",
    "AdenIntegrationInfo",
    # Client errors
    "AdenClientError",
    "AdenAuthenticationError",
    "AdenNotFoundError",
    "AdenRateLimitError",
    "AdenRefreshError",
    # Provider
    "AdenSyncProvider",
    # Storage
    "AdenCachedStorage",
]
