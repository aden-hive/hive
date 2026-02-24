"""
Credential Store - Production-ready credential management for Hive.

This module provides secure credential storage with:
- Key-vault structure: Credentials as objects with multiple keys
- Template-based usage: {{cred.key}} patterns for injection
- Bipartisan model: Store stores values, tools define usage
- Provider system: Extensible lifecycle management (refresh, validate)
- Multiple backends: Encrypted files, env vars, HashiCorp Vault

Quick Start:
    from core.framework.credentials import CredentialStore, CredentialObject

    # Create store with encrypted storage
    store = CredentialStore.with_encrypted_storage()  # defaults to ~/.hive/credentials

    # Get a credential
    api_key = store.get("brave_search")

    # Resolve templates in headers
    headers = store.resolve_headers({
        "Authorization": "Bearer {{github_oauth.access_token}}"
    })

    # Save a new credential
    store.save_credential(CredentialObject(
        id="my_api",
        keys={"api_key": CredentialKey(name="api_key", value=SecretStr("xxx"))}
    ))

For OAuth2 support:
    from core.framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config

For Aden server sync:
    from core.framework.credentials.aden import (
        AdenCredentialClient,
        AdenClientConfig,
        AdenSyncProvider,
    )

For Vault integration:
    from core.framework.credentials.vault import HashiCorpVaultStorage
"""

from .models import (
    CredentialDecryptionError,
    CredentialError,
    CredentialKey,
    CredentialKeyNotFoundError,
    CredentialNotFoundError,
    CredentialObject,
    CredentialRefreshError,
    CredentialType,
    CredentialUsageSpec,
    CredentialValidationError,
)
from .provider import (
    BearerTokenProvider,
    CredentialProvider,
    StaticProvider,
)
from .setup import (
    CredentialSetupSession,
    MissingCredential,
    SetupResult,
    detect_missing_credentials_from_nodes,
    run_credential_setup_cli,
)
from .storage import (
    CompositeStorage,
    CredentialStorage,
    EncryptedFileStorage,
    EnvVarStorage,
    InMemoryStorage,
)
from .store import CredentialStore
from .template import TemplateResolver
from .validation import ensure_credential_key_env, validate_agent_credentials

# Aden sync components (lazy import to avoid httpx dependency when not needed)
# Usage: from core.framework.credentials.aden import AdenSyncProvider
# Or: from core.framework.credentials import AdenSyncProvider
try:
    from .aden import (
        AdenCachedStorage,
        AdenClientConfig,
        AdenCredentialClient,
        AdenSyncProvider,
    )

    _ADEN_AVAILABLE = True
except ImportError:
    _ADEN_AVAILABLE = False

# Local credential registry (named API key accounts with identity metadata)
try:
    from .local import LocalAccountInfo, LocalCredentialRegistry

    _LOCAL_AVAILABLE = True
except ImportError:
    _LOCAL_AVAILABLE = False

__all__ = [
    # Main store
    "CredentialStore",
    # Models
    "CredentialObject",
    "CredentialKey",
    "CredentialType",
    "CredentialUsageSpec",
    # Providers
    "CredentialProvider",
    "StaticProvider",
    "BearerTokenProvider",
    # Storage backends
    "CredentialStorage",
    "EncryptedFileStorage",
    "EnvVarStorage",
    "InMemoryStorage",
    "CompositeStorage",
    # Template resolution
    "TemplateResolver",
    # Exceptions
    "CredentialError",
    "CredentialNotFoundError",
    "CredentialKeyNotFoundError",
    "CredentialRefreshError",
    "CredentialValidationError",
    "CredentialDecryptionError",
    # Validation
    "ensure_credential_key_env",
    "validate_agent_credentials",
    # Interactive setup
    "CredentialSetupSession",
    "MissingCredential",
    "SetupResult",
    "detect_missing_credentials_from_nodes",
    "run_credential_setup_cli",
    # Aden sync (optional - requires httpx)
    "AdenSyncProvider",
    "AdenCredentialClient",
    "AdenClientConfig",
    "AdenCachedStorage",
    # Local credential registry (optional - requires cryptography)
    "LocalCredentialRegistry",
    "LocalAccountInfo",
]

# Track Aden availability for runtime checks
ADEN_AVAILABLE = _ADEN_AVAILABLE
LOCAL_AVAILABLE = _LOCAL_AVAILABLE
