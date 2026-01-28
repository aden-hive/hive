# Credential Store Usage Guide

This guide covers how to use the Hive credential store for managing API keys, OAuth2 tokens, and custom credentials in your agents and tools.

## Table of Contents

- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Basic Usage](#basic-usage)
- [Template Resolution](#template-resolution)
- [Storage Backends](#storage-backends)
- [Using OAuth2 Provider](#using-oauth2-provider)
- [Implementing Custom Providers](#implementing-custom-providers)
- [Testing with Credentials](#testing-with-credentials)
- [Migration from CredentialManager](#migration-from-credentialmanager)
- [Security Best Practices](#security-best-practices)

---

## Quick Start

```python
from core.framework.credentials import CredentialStore, InMemoryStorage

# Create a store with in-memory storage (for development)
store = CredentialStore(storage=InMemoryStorage())

# Save a simple API key
store.save_api_key("brave_search", "your-api-key-here")

# Retrieve the credential
api_key = store.get("brave_search")

# Use template resolution for HTTP headers
headers = store.resolve_headers({
    "X-Subscription-Token": "{{brave_search.api_key}}"
})
# Result: {"X-Subscription-Token": "your-api-key-here"}
```

---

## Core Concepts

### Key-Vault Structure

Credentials are stored as **objects** containing one or more **keys**:

```
brave_search (CredentialObject)
├── api_key: "BSAKxxxxx"

github_oauth (CredentialObject)
├── access_token: "ghp_xxxxx"
├── refresh_token: "ghr_xxxxx"
└── expires_at: 2024-01-15T10:00:00Z
```

### Bipartisan Model

The credential store follows a **bipartisan model**:
- **Store**: Only stores credential values
- **Tools**: Define how credentials are used (headers, query params, etc.)

This separation keeps the store simple and lets each tool specify its exact requirements.

### Components

| Component | Purpose |
|-----------|---------|
| `CredentialStore` | Main orchestrator for all credential operations |
| `CredentialObject` | A credential with one or more keys |
| `CredentialKey` | A single key-value pair with optional expiration |
| `CredentialStorage` | Backend for persisting credentials |
| `CredentialProvider` | Handles credential lifecycle (refresh, validate) |
| `TemplateResolver` | Resolves `{{cred.key}}` patterns |

---

## Basic Usage

### Creating a Credential Store

```python
from core.framework.credentials import (
    CredentialStore,
    EncryptedFileStorage,
    EnvVarStorage,
    InMemoryStorage,
)

# Option 1: Encrypted file storage (recommended for production)
store = CredentialStore.with_encrypted_storage("/var/hive/credentials")

# Option 2: Environment variable storage (backward compatible)
store = CredentialStore.with_env_storage({
    "brave_search": "BRAVE_SEARCH_API_KEY",
    "openai": "OPENAI_API_KEY",
})

# Option 3: In-memory storage (for testing/development)
store = CredentialStore(storage=InMemoryStorage())

# Option 4: Custom storage configuration
storage = EncryptedFileStorage(
    base_path="/var/hive/credentials",
    key_env_var="HIVE_CREDENTIAL_KEY"  # Encryption key from env
)
store = CredentialStore(storage=storage)
```

### Saving Credentials

```python
# Simple API key
store.save_api_key("brave_search", "your-api-key")

# Multi-key credential (e.g., OAuth2)
from core.framework.credentials import CredentialObject, CredentialKey, CredentialType
from pydantic import SecretStr
from datetime import datetime, timedelta, timezone

credential = CredentialObject(
    id="github_oauth",
    credential_type=CredentialType.OAUTH2,
    keys={
        "access_token": CredentialKey(
            name="access_token",
            value=SecretStr("ghp_xxxxxxxxxxxx"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        ),
        "refresh_token": CredentialKey(
            name="refresh_token",
            value=SecretStr("ghr_xxxxxxxxxxxx")
        ),
    },
    provider_id="oauth2",
    auto_refresh=True,
)
store.save_credential(credential)
```

### Retrieving Credentials

```python
# Get the default key value (api_key, access_token, or first key)
api_key = store.get("brave_search")

# Get a specific key
access_token = store.get_key("github_oauth", "access_token")
refresh_token = store.get_key("github_oauth", "refresh_token")

# Get the full credential object
credential = store.get_credential("github_oauth")
if credential:
    print(f"Type: {credential.credential_type}")
    print(f"Keys: {list(credential.keys.keys())}")
    print(f"Auto-refresh: {credential.auto_refresh}")

# Check if credential exists and is available
if store.is_available("brave_search"):
    # Use the credential
    pass
```

### Deleting Credentials

```python
# Delete a credential
deleted = store.delete_credential("old_api_key")
if deleted:
    print("Credential deleted")
```

---

## Template Resolution

The credential store supports template patterns for injecting credentials into HTTP requests.

### Syntax

```
{{credential_id}}           -> Returns default key
{{credential_id.key_name}}  -> Returns specific key
```

### Resolving Headers

```python
# Define headers with credential templates
header_templates = {
    "Authorization": "Bearer {{github_oauth.access_token}}",
    "X-API-Key": "{{brave_search.api_key}}",
    "X-Custom": "{{custom_cred.token}}"
}

# Resolve to actual values
headers = store.resolve_headers(header_templates)
# Result: {
#     "Authorization": "Bearer ghp_xxxxxxxxxxxx",
#     "X-API-Key": "BSAKxxxxxxxxxxxx",
#     "X-Custom": "actual-token-value"
# }

# Use with httpx/requests
import httpx
response = httpx.get("https://api.example.com/data", headers=headers)
```

### Resolving Query Parameters

```python
params = store.resolve_params({
    "api_key": "{{brave_search.api_key}}",
    "client_id": "{{oauth_app.client_id}}"
})
```

### Resolving Arbitrary Strings

```python
# Resolve any string containing templates
url = store.resolve("https://api.example.com?key={{api_cred.key}}")
```

### Handling Missing Credentials

```python
# By default, missing credentials raise an error
try:
    headers = store.resolve_headers({"Auth": "{{missing.key}}"})
except CredentialNotFoundError as e:
    print(f"Missing credential: {e}")

# Use fail_on_missing=False to leave templates unresolved
headers = store.resolve_headers(
    {"Auth": "{{missing.key}}"},
    fail_on_missing=False
)
# Result: {"Auth": "{{missing.key}}"}
```

---

## Storage Backends

### EncryptedFileStorage (Recommended)

Encrypts credentials at rest using Fernet (AES-128-CBC + HMAC).

```python
from core.framework.credentials import EncryptedFileStorage

# The encryption key is read from HIVE_CREDENTIAL_KEY env var
storage = EncryptedFileStorage("/var/hive/credentials")

# Or provide the key directly (32-byte Fernet key)
storage = EncryptedFileStorage(
    base_path="/var/hive/credentials",
    encryption_key=b"your-32-byte-fernet-key-here..."
)
```

**Directory structure:**
```
/var/hive/credentials/
├── credentials/
│   ├── brave_search.enc    # Encrypted credential JSON
│   └── github_oauth.enc
└── metadata/
    └── index.json          # Unencrypted index
```

**Generate an encryption key:**
```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(f"HIVE_CREDENTIAL_KEY={key.decode()}")
```

### EnvVarStorage (Backward Compatible)

Reads credentials from environment variables. **Read-only** - cannot save credentials.

```python
from core.framework.credentials import EnvVarStorage

storage = EnvVarStorage(
    env_mapping={
        "brave_search": "BRAVE_SEARCH_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
)

# Credentials are read from environment
# export BRAVE_SEARCH_API_KEY=your-key
```

### CompositeStorage (Layered)

Combines multiple storage backends with fallback.

```python
from core.framework.credentials import CompositeStorage, EncryptedFileStorage, EnvVarStorage

storage = CompositeStorage(
    primary=EncryptedFileStorage("/var/hive/credentials"),
    fallbacks=[
        EnvVarStorage({"brave_search": "BRAVE_SEARCH_API_KEY"})
    ]
)

# Writes go to primary (encrypted files)
# Reads check primary first, then fallbacks (env vars)
```

### HashiCorp Vault Storage

For enterprise deployments with HashiCorp Vault.

```python
from core.framework.credentials.vault import HashiCorpVaultStorage

storage = HashiCorpVaultStorage(
    vault_url="https://vault.example.com",
    token="hvs.xxxxx",  # Or use VAULT_TOKEN env var
    mount_point="secret",
    path_prefix="hive/credentials"
)
```

---

## Using OAuth2 Provider

The OAuth2 provider handles token lifecycle including automatic refresh.

### Setup

```python
from core.framework.credentials import CredentialStore, InMemoryStorage
from core.framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config

# Configure OAuth2
config = OAuth2Config(
    token_url="https://oauth.example.com/token",
    authorization_url="https://oauth.example.com/authorize",  # Optional
    client_id="your-client-id",
    client_secret="your-client-secret",
    default_scopes=["read", "write"],
)

# Create provider
provider = BaseOAuth2Provider(config)

# Create store with provider
store = CredentialStore(
    storage=InMemoryStorage(),
    providers=[provider],
)
```

### Client Credentials Flow (Server-to-Server)

```python
# Get a token using client credentials
token = provider.client_credentials_grant(scopes=["api.read"])

# Save to store
from core.framework.credentials import CredentialObject, CredentialKey, CredentialType
from pydantic import SecretStr

credential = CredentialObject(
    id="service_account",
    credential_type=CredentialType.OAUTH2,
    keys={
        "access_token": CredentialKey(
            name="access_token",
            value=SecretStr(token.access_token),
            expires_at=token.expires_at
        ),
    },
    provider_id="oauth2",
    auto_refresh=True,
)
store.save_credential(credential)
```

### Refresh Token Flow

```python
# Save credential with refresh token
credential = CredentialObject(
    id="user_oauth",
    credential_type=CredentialType.OAUTH2,
    keys={
        "access_token": CredentialKey(
            name="access_token",
            value=SecretStr("ghp_xxxx"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        ),
        "refresh_token": CredentialKey(
            name="refresh_token",
            value=SecretStr("ghr_xxxx")
        ),
    },
    provider_id="oauth2",
    auto_refresh=True,
)
store.save_credential(credential)

# When you retrieve the credential, it auto-refreshes if expired
token = store.get("user_oauth")  # Automatically refreshed if needed

# Or manually refresh
store.refresh_credential("user_oauth")
```

### Token Lifecycle Manager

For more control over token lifecycle:

```python
from core.framework.credentials.oauth2 import TokenLifecycleManager
from datetime import timedelta

manager = TokenLifecycleManager(
    credential_id="my_oauth",
    provider=provider,
    store=store,
    refresh_buffer=timedelta(minutes=5),  # Refresh 5 min before expiry
)

# Acquire token (refreshes if needed)
token = await manager.acquire_token()

# Use the token
headers = {"Authorization": f"Bearer {token.access_token}"}
```

---

## Implementing Custom Providers

Custom providers let you integrate with proprietary authentication systems.

### Provider Interface

```python
from abc import ABC, abstractmethod
from typing import List
from core.framework.credentials import CredentialObject, CredentialType

class CredentialProvider(ABC):
    """Abstract base for credential providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider."""
        pass

    @property
    @abstractmethod
    def supported_types(self) -> List[CredentialType]:
        """Credential types this provider handles."""
        pass

    @abstractmethod
    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """Refresh the credential and return updated version."""
        pass

    @abstractmethod
    def validate(self, credential: CredentialObject) -> bool:
        """Check if credential is still valid."""
        pass

    def should_refresh(self, credential: CredentialObject) -> bool:
        """Determine if credential needs refresh (optional override)."""
        # Default: check expiration with 5-minute buffer
        ...

    def revoke(self, credential: CredentialObject) -> bool:
        """Revoke credential (optional, default returns False)."""
        return False
```

### Example: Custom API Provider

```python
from datetime import datetime, timedelta, timezone
from typing import List

from pydantic import SecretStr

from core.framework.credentials import (
    CredentialKey,
    CredentialObject,
    CredentialProvider,
    CredentialRefreshError,
    CredentialType,
)


class MyCustomProvider(CredentialProvider):
    """
    Custom provider for MyService API tokens.

    MyService issues tokens that expire after 24 hours and can be
    refreshed using the original API key.
    """

    def __init__(self, base_url: str = "https://api.myservice.com"):
        self.base_url = base_url

    @property
    def provider_id(self) -> str:
        return "myservice"

    @property
    def supported_types(self) -> List[CredentialType]:
        return [CredentialType.CUSTOM]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """Refresh the access token using the API key."""
        import httpx

        api_key = credential.get_key("api_key")
        if not api_key:
            raise CredentialRefreshError(
                f"Credential '{credential.id}' missing api_key for refresh"
            )

        # Call MyService API to get new token
        try:
            response = httpx.post(
                f"{self.base_url}/auth/token",
                headers={"X-API-Key": api_key},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise CredentialRefreshError(f"Token refresh failed: {e}") from e

        # Update credential with new token
        credential.set_key(
            "access_token",
            data["access_token"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        credential.last_refreshed = datetime.now(timezone.utc)

        return credential

    def validate(self, credential: CredentialObject) -> bool:
        """Check if access_token exists and is not expired."""
        access_key = credential.keys.get("access_token")
        if access_key is None:
            return False
        return not access_key.is_expired

    def should_refresh(self, credential: CredentialObject) -> bool:
        """Refresh if token expires within 1 hour."""
        access_key = credential.keys.get("access_token")
        if access_key is None or access_key.expires_at is None:
            return False

        buffer = timedelta(hours=1)
        return datetime.now(timezone.utc) >= (access_key.expires_at - buffer)

    def revoke(self, credential: CredentialObject) -> bool:
        """Revoke the access token."""
        import httpx

        access_token = credential.get_key("access_token")
        if not access_token:
            return False

        try:
            response = httpx.post(
                f"{self.base_url}/auth/revoke",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False
```

### Registering Custom Providers

```python
from core.framework.credentials import CredentialStore, InMemoryStorage

# Create store with custom provider
provider = MyCustomProvider(base_url="https://api.myservice.com")
store = CredentialStore(
    storage=InMemoryStorage(),
    providers=[provider],
)

# Or register after creation
store.register_provider(provider)

# Save a credential that uses this provider
credential = CredentialObject(
    id="myservice_prod",
    credential_type=CredentialType.CUSTOM,
    keys={
        "api_key": CredentialKey(
            name="api_key",
            value=SecretStr("my-permanent-api-key")
        ),
    },
    provider_id="myservice",  # Links to our custom provider
    auto_refresh=True,
)
store.save_credential(credential)

# The store will use MyCustomProvider for refresh/validate
token = store.get("myservice_prod")  # Auto-refreshes if needed
```

### Example: Extending OAuth2 for a Specific Service

```python
from core.framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config, OAuth2Token


class GitHubOAuth2Provider(BaseOAuth2Provider):
    """GitHub-specific OAuth2 provider with custom scopes handling."""

    def __init__(self, client_id: str, client_secret: str):
        config = OAuth2Config(
            token_url="https://github.com/login/oauth/access_token",
            authorization_url="https://github.com/login/oauth/authorize",
            client_id=client_id,
            client_secret=client_secret,
            default_scopes=["repo", "read:user"],
        )
        super().__init__(config)

    @property
    def provider_id(self) -> str:
        return "github_oauth2"

    def _parse_token_response(self, response_data: dict) -> OAuth2Token:
        """GitHub returns scope as space-separated string."""
        token = super()._parse_token_response(response_data)

        # GitHub-specific: tokens don't expire unless revoked
        # But we set a reasonable refresh interval
        if token.expires_at is None:
            token.expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        return token

    def validate(self, credential: CredentialObject) -> bool:
        """Validate by making a test API call to GitHub."""
        import httpx

        access_token = credential.get_key("access_token")
        if not access_token:
            return False

        try:
            response = httpx.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False
```

---

## Testing with Credentials

### Using the Testing Factory

```python
from core.framework.credentials import CredentialStore

# Create a test store with mock credentials
store = CredentialStore.for_testing({
    "brave_search": {"api_key": "test-brave-key"},
    "github_oauth": {
        "access_token": "test-github-token",
        "refresh_token": "test-refresh-token",
    },
})

# Use in tests
def test_my_tool():
    api_key = store.get("brave_search")
    assert api_key == "test-brave-key"

    headers = store.resolve_headers({
        "Authorization": "Bearer {{github_oauth.access_token}}"
    })
    assert headers["Authorization"] == "Bearer test-github-token"
```

### Using with CredentialStoreAdapter (Backward Compatible)

```python
from aden_tools.credentials import CredentialStoreAdapter

# For testing existing tools
credentials = CredentialStoreAdapter.for_testing({
    "brave_search": "test-key",
    "openai": "test-openai-key",
})

# Existing API works
assert credentials.get("brave_search") == "test-key"
credentials.validate_for_tools(["web_search"])  # No error
```

### Mocking in Unit Tests

```python
import pytest
from unittest.mock import MagicMock, patch

def test_tool_with_mocked_store():
    # Create a mock store
    mock_store = MagicMock()
    mock_store.get.return_value = "mocked-api-key"
    mock_store.resolve_headers.return_value = {
        "Authorization": "Bearer mocked-token"
    }

    # Inject into your tool
    with patch("my_tool.credential_store", mock_store):
        result = my_tool.make_api_call()
        mock_store.get.assert_called_once_with("api_credential")
```

---

## Migration from CredentialManager

If you're using the existing `CredentialManager`, migration is straightforward.

### Option 1: Use the Adapter (No Code Changes)

```python
# Before
from aden_tools.credentials import CredentialManager
credentials = CredentialManager()

# After - using adapter with new store backend
from aden_tools.credentials import CredentialStoreAdapter
from core.framework.credentials import CredentialStore

store = CredentialStore.with_encrypted_storage("/var/hive/credentials")
credentials = CredentialStoreAdapter(store)

# All existing code works unchanged
api_key = credentials.get("brave_search")
credentials.validate_for_tools(["web_search"])
```

### Option 2: Use Environment Storage (Identical Behavior)

```python
from aden_tools.credentials import CredentialStoreAdapter

# Creates adapter backed by environment variables
credentials = CredentialStoreAdapter.with_env_storage()

# Behaves exactly like original CredentialManager
api_key = credentials.get("brave_search")
```

### Option 3: Gradual Migration

```python
from aden_tools.credentials import CredentialStoreAdapter
from core.framework.credentials import CredentialStore, CompositeStorage, EncryptedFileStorage, EnvVarStorage

# Use encrypted storage as primary, env vars as fallback
storage = CompositeStorage(
    primary=EncryptedFileStorage("/var/hive/credentials"),
    fallbacks=[EnvVarStorage({"brave_search": "BRAVE_SEARCH_API_KEY"})]
)

store = CredentialStore(storage=storage)
credentials = CredentialStoreAdapter(store)

# New credentials go to encrypted storage
# Old env var credentials still work as fallback
```

---

## Security Best Practices

### 1. Use Encrypted Storage in Production

```python
# Always use EncryptedFileStorage for production
store = CredentialStore.with_encrypted_storage("/var/hive/credentials")
```

### 2. Protect the Encryption Key

```bash
# Set encryption key as environment variable
export HIVE_CREDENTIAL_KEY="your-fernet-key"

# Or use a secrets manager
export HIVE_CREDENTIAL_KEY=$(vault kv get -field=key secret/hive/credential-key)
```

### 3. Use SecretStr for Values

```python
from pydantic import SecretStr

# SecretStr prevents accidental logging
key = CredentialKey(
    name="api_key",
    value=SecretStr("sensitive-value")  # Won't appear in logs
)

# Explicitly extract when needed
actual_value = key.get_secret_value()
```

### 4. Set Appropriate Expiration

```python
# Always set expiration for tokens
credential.set_key(
    "access_token",
    token_value,
    expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
)
```

### 5. Enable Auto-Refresh

```python
credential = CredentialObject(
    id="my_oauth",
    auto_refresh=True,  # Automatically refresh before expiry
    provider_id="oauth2",
    ...
)
```

### 6. Validate Before Use

```python
# Check credential validity before making API calls
if not store.is_available("api_credential"):
    raise RuntimeError("Required credential not available")

# Or use validation
errors = store.validate_for_usage("api_credential")
if errors:
    raise RuntimeError(f"Credential validation failed: {errors}")
```

### 7. Use Template Resolution

```python
# Don't interpolate secrets manually
# Bad:
headers = {"Authorization": f"Bearer {store.get('token')}"}

# Good - uses template resolution which handles errors gracefully:
headers = store.resolve_headers({
    "Authorization": "Bearer {{my_oauth.access_token}}"
})
```

---

## API Reference

### CredentialStore

| Method | Description |
|--------|-------------|
| `get(credential_id)` | Get default key value |
| `get_key(credential_id, key_name)` | Get specific key value |
| `get_credential(credential_id)` | Get full credential object |
| `save_credential(credential)` | Save credential to storage |
| `save_api_key(id, value)` | Convenience for simple API keys |
| `delete_credential(credential_id)` | Delete a credential |
| `is_available(credential_id)` | Check if credential exists and has value |
| `resolve(template)` | Resolve template string |
| `resolve_headers(headers)` | Resolve templates in headers dict |
| `resolve_params(params)` | Resolve templates in params dict |
| `refresh_credential(credential_id)` | Manually refresh a credential |
| `register_provider(provider)` | Register a custom provider |
| `for_testing(credentials)` | Create test store with mock data |
| `with_encrypted_storage(path)` | Create store with encrypted files |
| `with_env_storage(mapping)` | Create store with env var backend |

### CredentialObject

| Property/Method | Description |
|-----------------|-------------|
| `id` | Unique identifier |
| `credential_type` | Type (API_KEY, OAUTH2, etc.) |
| `keys` | Dict of CredentialKey objects |
| `get_key(name)` | Get key value by name |
| `set_key(name, value, ...)` | Set or update a key |
| `has_key(name)` | Check if key exists |
| `get_default_key()` | Get default key value |
| `needs_refresh` | True if any key is expired |
| `is_valid` | True if has valid, non-expired key |
| `auto_refresh` | Whether to auto-refresh |
| `provider_id` | ID of provider for lifecycle |

### CredentialProvider

| Method | Description |
|--------|-------------|
| `provider_id` | Unique identifier (property) |
| `supported_types` | List of supported CredentialTypes (property) |
| `refresh(credential)` | Refresh and return updated credential |
| `validate(credential)` | Check if credential is valid |
| `should_refresh(credential)` | Check if refresh is needed |
| `revoke(credential)` | Revoke credential (optional) |

---

## Troubleshooting

### "Unknown credential" Error

```python
# Error: KeyError: "Unknown credential 'my_cred'"

# Solution: Check if credential exists
if store.get_credential("my_cred") is None:
    print("Credential not found - need to save it first")
```

### "Credential not found" in Templates

```python
# Error: CredentialNotFoundError when resolving templates

# Solution 1: Ensure credential is saved
store.save_api_key("my_cred", "value")

# Solution 2: Use fail_on_missing=False
headers = store.resolve_headers(templates, fail_on_missing=False)
```

### Encryption Key Issues

```python
# Error: "Failed to decrypt credential"

# Solution: Ensure HIVE_CREDENTIAL_KEY matches what was used to encrypt
# If key is lost, credentials must be re-created
```

### Provider Not Found

```python
# Warning: "No provider found for credential 'x'"

# Solution: Register the provider or set provider_id=None for static credentials
store.register_provider(MyProvider())

# Or use static provider (default)
credential.provider_id = "static"  # or None
```

---

## Further Reading

- [Credential Store Design Document](credential-store-design.md)
- [OAuth2 RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)
- [Fernet Encryption](https://cryptography.io/en/latest/fernet/)
