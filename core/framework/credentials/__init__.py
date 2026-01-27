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
    store = CredentialStore.with_encrypted_storage("/var/hive/credentials")

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
from .storage import (
    CompositeStorage,
    CredentialStorage,
    EncryptedFileStorage,
    EnvVarStorage,
    InMemoryStorage,
)
from .store import CredentialStore
from .template import TemplateResolver

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
]
