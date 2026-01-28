# Production-Ready Credential Store Design

## Overview

This document describes the design for a production-ready credential store for the Hive agent framework. The system provides:

- **Key-vault structure**: Credentials as objects with multiple keys (e.g., `cred1.api_key`, `cred2.access_token`)
- **Template-based usage**: Tools specify `{{cred.key}}` patterns for injection into headers/params
- **Bipartisan model**: Store only stores values; tools define how they're used
- **Provider system**: Extensible providers (OAuth2, static, custom) for credential lifecycle management
- **OSS extensibility**: Interfaces for users to implement custom providers
- **External vault integration**: HashiCorp Vault adapter for enterprise deployments

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Data Models](#core-data-models)
3. [Template Resolution System](#template-resolution-system)
4. [Provider Interface](#provider-interface)
5. [Storage Backends](#storage-backends)
6. [Main Credential Store](#main-credential-store)
7. [OAuth2 Module](#oauth2-module)
8. [HashiCorp Vault Integration](#hashicorp-vault-integration)
9. [Backward Compatibility](#backward-compatibility)
10. [Usage Examples](#usage-examples)
11. [Implementation Plan](#implementation-plan)
12. [Security Considerations](#security-considerations)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CredentialStore                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Template Resolver                         │   │
│  │         {{cred.key}} → actual value resolution               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌────────────────┐  │
│  │ CredentialObject│    │ CredentialObject│    │CredentialObject│  │
│  │   brave_search  │    │  github_oauth   │    │  salesforce    │  │
│  │ ┌─────────────┐│    │ ┌─────────────┐ │    │ ┌────────────┐ │  │
│  │ │api_key: xxx ││    │ │access_token │ │    │ │access_token│ │  │
│  │ └─────────────┘│    │ │refresh_token│ │    │ │instance_url│ │  │
│  └─────────────────┘    │ │expires_at   │ │    │ └────────────┘ │  │
│                         │ └─────────────┘ │    └────────────────┘  │
│                         └─────────────────┘                         │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                       Providers                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │   │
│  │  │StaticProvider│  │OAuth2Provider│  │ CustomProvider   │   │   │
│  │  │ (no refresh) │  │(auto-refresh)│  │ (user-defined)   │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Storage Backends                           │   │
│  │  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐  │   │
│  │  │EncryptedFile   │  │  EnvVar        │  │HashiCorpVault │  │   │
│  │  │ (Fernet AES)   │  │  (read-only)   │  │  (external)   │  │   │
│  │  └────────────────┘  └────────────────┘  └───────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Core Data Models

**Location**: `core/framework/credentials/models.py`

### CredentialType

```python
from enum import Enum

class CredentialType(str, Enum):
    """Types of credentials the store can manage."""
    API_KEY = "api_key"           # Simple API key (e.g., Brave Search)
    OAUTH2 = "oauth2"             # OAuth2 with refresh support
    BASIC_AUTH = "basic_auth"     # Username/password pair
    BEARER_TOKEN = "bearer_token" # JWT or bearer token
    CUSTOM = "custom"             # User-defined credential type
```

### CredentialKey

```python
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, SecretStr, Field

class CredentialKey(BaseModel):
    """
    A single key within a credential object.

    Example: 'api_key' within a 'brave_search' credential
    """
    name: str
    value: SecretStr  # Prevents accidental logging
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if this key has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= self.expires_at

    def get_secret_value(self) -> str:
        """Get the actual secret value (use sparingly)."""
        return self.value.get_secret_value()
```

### CredentialObject

```python
class CredentialObject(BaseModel):
    """
    A credential object containing one or more keys.

    This is the key-vault structure where each credential can have
    multiple keys (e.g., access_token, refresh_token, expires_at).

    Example:
        CredentialObject(
            id="github_oauth",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(name="access_token", value="ghp_xxx"),
                "refresh_token": CredentialKey(name="refresh_token", value="ghr_xxx"),
            },
            provider_id="oauth2"
        )
    """
    id: str = Field(description="Unique identifier (e.g., 'brave_search', 'github_oauth')")
    credential_type: CredentialType = CredentialType.API_KEY
    keys: Dict[str, CredentialKey] = Field(default_factory=dict)

    # Lifecycle management
    provider_id: Optional[str] = Field(
        default=None,
        description="ID of provider responsible for lifecycle (e.g., 'oauth2')"
    )
    last_refreshed: Optional[datetime] = None
    auto_refresh: bool = False

    # Usage tracking
    last_used: Optional[datetime] = None
    use_count: int = 0

    # Metadata
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_key(self, key_name: str) -> Optional[str]:
        """Get a specific key's value."""
        key = self.keys.get(key_name)
        if key is None:
            return None
        return key.get_secret_value()

    def set_key(
        self,
        key_name: str,
        value: str,
        expires_at: Optional[datetime] = None
    ) -> None:
        """Set or update a key."""
        self.keys[key_name] = CredentialKey(
            name=key_name,
            value=SecretStr(value),
            expires_at=expires_at
        )
        self.updated_at = datetime.utcnow()

    @property
    def needs_refresh(self) -> bool:
        """Check if any key is expired or near expiration."""
        for key in self.keys.values():
            if key.is_expired:
                return True
        return False

    def record_usage(self) -> None:
        """Record that this credential was used."""
        self.last_used = datetime.utcnow()
        self.use_count += 1
```

### CredentialUsageSpec

```python
class CredentialUsageSpec(BaseModel):
    """
    Specification for how a tool uses credentials.

    This implements the "bipartisan" model where the credential store
    just stores values, and tools define how those values are used.

    Example:
        CredentialUsageSpec(
            credential_id="brave_search",
            required_keys=["api_key"],
            headers={"X-Subscription-Token": "{{api_key}}"}
        )
    """
    credential_id: str = Field(description="ID of credential to use")
    required_keys: list[str] = Field(
        default_factory=list,
        description="Keys that must be present (e.g., ['api_key'])"
    )

    # Injection templates (bipartisan model)
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Header templates (e.g., {'Authorization': 'Bearer {{access_token}}'})"
    )
    query_params: Dict[str, str] = Field(
        default_factory=dict,
        description="Query param templates (e.g., {'api_key': '{{api_key}}'})"
    )
    body_fields: Dict[str, str] = Field(
        default_factory=dict,
        description="Request body field templates"
    )

    required: bool = True
    description: str = ""
    help_url: str = ""
```

---

## Template Resolution System

**Location**: `core/framework/credentials/template.py`

The template resolver handles `{{cred.key}}` patterns, enabling the bipartisan model where tools specify how credentials are used.

### Template Syntax

| Pattern | Meaning | Example |
|---------|---------|---------|
| `{{credential_id.key_name}}` | Access specific key | `{{github_oauth.access_token}}` |
| `{{credential_id}}` | Access default key | `{{brave_search}}` → `api_key` value |

### TemplateResolver Class

```python
import re
from typing import Optional

class TemplateResolver:
    """
    Resolves credential templates like {{cred.key}} into actual values.

    Examples:
        "Bearer {{github_oauth.access_token}}" -> "Bearer ghp_xxx"
        "X-API-Key: {{brave_search.api_key}}"  -> "X-API-Key: BSAKxxx"
    """

    TEMPLATE_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}")

    def __init__(self, credential_store: "CredentialStore"):
        self._store = credential_store

    def resolve(self, template: str, fail_on_missing: bool = True) -> str:
        """
        Resolve all credential references in a template string.

        Args:
            template: String containing {{cred.key}} patterns
            fail_on_missing: If True, raise error on missing credentials

        Returns:
            Template with all references replaced with actual values

        Raises:
            CredentialNotFoundError: If credential doesn't exist
            CredentialKeyNotFoundError: If key doesn't exist in credential
        """
        def replace_match(match: re.Match) -> str:
            cred_id = match.group(1)
            key_name = match.group(2)  # May be None

            credential = self._store.get_credential(cred_id)
            if credential is None:
                if fail_on_missing:
                    raise CredentialNotFoundError(f"Credential '{cred_id}' not found")
                return match.group(0)

            # Get specific key or default
            if key_name:
                value = credential.get_key(key_name)
                if value is None:
                    raise CredentialKeyNotFoundError(
                        f"Key '{key_name}' not found in credential '{cred_id}'"
                    )
            else:
                # Default: use 'value', 'api_key', or first key
                value = self._get_default_key(credential)

            return value

        return self.TEMPLATE_PATTERN.sub(replace_match, template)

    def resolve_headers(
        self,
        header_templates: Dict[str, str],
        fail_on_missing: bool = True
    ) -> Dict[str, str]:
        """Resolve templates in a headers dictionary."""
        return {
            key: self.resolve(value, fail_on_missing)
            for key, value in header_templates.items()
        }

    def has_templates(self, text: str) -> bool:
        """Check if text contains any credential templates."""
        return bool(self.TEMPLATE_PATTERN.search(text))

    def extract_references(self, text: str) -> list[tuple[str, Optional[str]]]:
        """
        Extract all credential references from text.

        Returns list of (credential_id, key_name) tuples.
        """
        return [
            (match.group(1), match.group(2))
            for match in self.TEMPLATE_PATTERN.finditer(text)
        ]

    def _get_default_key(self, credential: CredentialObject) -> str:
        """Get the default key value for a credential."""
        for key_name in ["value", "api_key", "access_token"]:
            if key_name in credential.keys:
                return credential.get_key(key_name)

        if credential.keys:
            first_key = next(iter(credential.keys))
            return credential.get_key(first_key)

        raise CredentialKeyNotFoundError(
            f"Credential '{credential.id}' has no keys"
        )


class CredentialNotFoundError(Exception):
    """Raised when a referenced credential doesn't exist."""
    pass


class CredentialKeyNotFoundError(Exception):
    """Raised when a referenced key doesn't exist in a credential."""
    pass
```

---

## Provider Interface

**Location**: `core/framework/credentials/provider.py`

Providers handle credential lifecycle operations (refresh, validate, revoke).

### CredentialProvider ABC

```python
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List
import logging

logger = logging.getLogger(__name__)


class CredentialProvider(ABC):
    """
    Abstract base class for credential providers.

    Providers handle credential lifecycle operations:
    - Refresh: Obtain new tokens when expired
    - Validate: Check if credentials are still working
    - Revoke: Invalidate credentials when no longer needed

    OSS users can implement custom providers by subclassing this.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider (e.g., 'oauth2', 'static')."""
        pass

    @property
    @abstractmethod
    def supported_types(self) -> List[CredentialType]:
        """Credential types this provider can manage."""
        pass

    @abstractmethod
    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Refresh the credential (e.g., use refresh_token to get new access_token).

        Args:
            credential: The credential to refresh

        Returns:
            Updated credential with new values

        Raises:
            CredentialRefreshError: If refresh fails
        """
        pass

    @abstractmethod
    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate that a credential is still working.

        Args:
            credential: The credential to validate

        Returns:
            True if credential is valid, False otherwise
        """
        pass

    def should_refresh(self, credential: CredentialObject) -> bool:
        """
        Determine if a credential should be refreshed.

        Default: refresh if any key is expired or within 5 minutes of expiry.
        Override for custom logic.
        """
        buffer = timedelta(minutes=5)
        now = datetime.utcnow()

        for key in credential.keys.values():
            if key.expires_at is not None:
                if key.expires_at <= now + buffer:
                    return True
        return False

    def revoke(self, credential: CredentialObject) -> bool:
        """
        Revoke a credential (optional operation).

        Returns:
            True if revocation succeeded, False otherwise
        """
        logger.warning(f"Provider {self.provider_id} does not support revocation")
        return False


class CredentialRefreshError(Exception):
    """Raised when credential refresh fails."""
    pass
```

### StaticProvider

```python
class StaticProvider(CredentialProvider):
    """
    Provider for static credentials that never need refresh.

    Use for simple API keys that don't expire.
    """

    @property
    def provider_id(self) -> str:
        return "static"

    @property
    def supported_types(self) -> List[CredentialType]:
        return [CredentialType.API_KEY, CredentialType.CUSTOM]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        # Static credentials don't refresh
        return credential

    def validate(self, credential: CredentialObject) -> bool:
        # Static credentials are always "valid" from our perspective
        return len(credential.keys) > 0

    def should_refresh(self, credential: CredentialObject) -> bool:
        return False  # Never refresh
```

---

## Storage Backends

**Location**: `core/framework/credentials/storage.py`

### CredentialStorage ABC

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class CredentialStorage(ABC):
    """
    Abstract storage backend for credentials.

    Implementations:
    - EncryptedFileStorage: Local encrypted JSON files (default)
    - EnvVarStorage: Environment variables (backward compatibility)
    - HashiCorpVaultStorage: HashiCorp Vault integration
    """

    @abstractmethod
    def save(self, credential: CredentialObject) -> None:
        """Save a credential to storage."""
        pass

    @abstractmethod
    def load(self, credential_id: str) -> Optional[CredentialObject]:
        """Load a credential from storage."""
        pass

    @abstractmethod
    def delete(self, credential_id: str) -> bool:
        """Delete a credential. Returns True if existed."""
        pass

    @abstractmethod
    def list_all(self) -> List[str]:
        """List all credential IDs."""
        pass

    @abstractmethod
    def exists(self, credential_id: str) -> bool:
        """Check if a credential exists."""
        pass
```

### EncryptedFileStorage

```python
from pathlib import Path
import json

class EncryptedFileStorage(CredentialStorage):
    """
    Encrypted file-based credential storage.

    Uses Fernet symmetric encryption (AES-128-CBC + HMAC).
    Stores each credential as a separate encrypted JSON file.

    Directory structure:
        {base_path}/
            credentials/
                {credential_id}.enc   # Encrypted credential JSON
            metadata/
                index.json            # Index of all credentials

    Encryption key is read from HIVE_CREDENTIAL_KEY environment variable.
    """

    def __init__(
        self,
        base_path: str | Path,
        encryption_key: Optional[bytes] = None,
        key_env_var: str = "HIVE_CREDENTIAL_KEY"
    ):
        """
        Initialize encrypted storage.

        Args:
            base_path: Directory for credential files
            encryption_key: 32-byte Fernet key. If None, reads from env var.
            key_env_var: Environment variable containing encryption key
        """
        from cryptography.fernet import Fernet
        import os

        self.base_path = Path(base_path)
        self._ensure_dirs()

        # Get or generate encryption key
        if encryption_key:
            self._key = encryption_key
        else:
            key_str = os.environ.get(key_env_var)
            if key_str:
                self._key = key_str.encode()
            else:
                # Generate new key (user must persist this!)
                self._key = Fernet.generate_key()
                logger.warning(
                    f"Generated new encryption key. "
                    f"Set {key_env_var}={self._key.decode()} to persist credentials."
                )

        self._fernet = Fernet(self._key)

    def save(self, credential: CredentialObject) -> None:
        """Encrypt and save credential."""
        data = self._serialize_credential(credential)
        json_bytes = json.dumps(data).encode()
        encrypted = self._fernet.encrypt(json_bytes)

        cred_path = self._cred_path(credential.id)
        with open(cred_path, "wb") as f:
            f.write(encrypted)

        self._update_index(credential.id, "save")

    def load(self, credential_id: str) -> Optional[CredentialObject]:
        """Load and decrypt credential."""
        cred_path = self._cred_path(credential_id)
        if not cred_path.exists():
            return None

        with open(cred_path, "rb") as f:
            encrypted = f.read()

        try:
            json_bytes = self._fernet.decrypt(encrypted)
            data = json.loads(json_bytes.decode())
        except Exception as e:
            raise CredentialDecryptionError(
                f"Failed to decrypt credential '{credential_id}': {e}"
            )

        return self._deserialize_credential(data)

    def delete(self, credential_id: str) -> bool:
        """Delete a credential file."""
        cred_path = self._cred_path(credential_id)
        if cred_path.exists():
            cred_path.unlink()
            self._update_index(credential_id, "delete")
            return True
        return False

    def list_all(self) -> List[str]:
        """List all credential IDs."""
        index_path = self.base_path / "metadata" / "index.json"
        if not index_path.exists():
            return []
        with open(index_path) as f:
            index = json.load(f)
        return list(index.get("credentials", {}).keys())

    def exists(self, credential_id: str) -> bool:
        return self._cred_path(credential_id).exists()

    # ... helper methods ...


class CredentialDecryptionError(Exception):
    """Raised when credential decryption fails."""
    pass
```

### EnvVarStorage (Backward Compatibility)

```python
class EnvVarStorage(CredentialStorage):
    """
    Environment variable-based storage for backward compatibility.

    Maps credential IDs to environment variable patterns.
    Single-key credentials only. Read-only (cannot save).

    Supports hot-reload from .env files.
    """

    def __init__(
        self,
        env_mapping: Optional[Dict[str, str]] = None,
        dotenv_path: Optional[Path] = None
    ):
        """
        Args:
            env_mapping: Map of credential_id -> env_var_name
                        e.g., {"brave_search": "BRAVE_SEARCH_API_KEY"}
            dotenv_path: Path to .env file for hot-reload
        """
        self._env_mapping = env_mapping or {}
        self._dotenv_path = dotenv_path or Path.cwd() / ".env"

    def save(self, credential: CredentialObject) -> None:
        """Cannot save to environment variables at runtime."""
        raise NotImplementedError(
            "EnvVarStorage is read-only. Set environment variables externally."
        )

    def load(self, credential_id: str) -> Optional[CredentialObject]:
        """Load credential from environment variable."""
        import os
        from dotenv import dotenv_values

        env_var = self._env_mapping.get(credential_id)
        if not env_var:
            env_var = f"{credential_id.upper()}_API_KEY"

        # Check os.environ first, then .env file
        value = os.environ.get(env_var)
        if not value and self._dotenv_path.exists():
            values = dotenv_values(self._dotenv_path)
            value = values.get(env_var)

        if not value:
            return None

        return CredentialObject(
            id=credential_id,
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr(value))}
        )

    # ... other methods ...
```

---

## Main Credential Store

**Location**: `core/framework/credentials/store.py`

```python
import threading
from typing import Dict, List, Optional
from datetime import datetime


class CredentialStore:
    """
    Main credential store orchestrating storage, providers, and template resolution.

    Features:
    - Multi-backend storage (file, env, vault)
    - Provider-based lifecycle management (refresh, validate)
    - Template resolution for {{cred.key}} patterns
    - Caching with TTL for performance
    - Thread-safe operations

    Usage:
        store = CredentialStore(
            storage=EncryptedFileStorage("/path/to/creds"),
            providers=[OAuth2Provider(), StaticProvider()]
        )

        # Get a credential
        cred = store.get_credential("github_oauth")

        # Resolve templates in headers
        headers = store.resolve_headers({
            "Authorization": "Bearer {{github_oauth.access_token}}"
        })

        # Register a tool's credential requirements
        store.register_usage(CredentialUsageSpec(
            credential_id="brave_search",
            required_keys=["api_key"],
            headers={"X-Subscription-Token": "{{brave_search.api_key}}"}
        ))
    """

    def __init__(
        self,
        storage: Optional[CredentialStorage] = None,
        providers: Optional[List[CredentialProvider]] = None,
        cache_ttl_seconds: int = 300,
        auto_refresh: bool = True,
    ):
        """
        Initialize the credential store.

        Args:
            storage: Storage backend. Defaults to EnvVarStorage.
            providers: List of credential providers. Defaults to [StaticProvider()].
            cache_ttl_seconds: How long to cache credentials in memory.
            auto_refresh: Whether to auto-refresh expired credentials.
        """
        self._storage = storage or EnvVarStorage()
        self._providers: Dict[str, CredentialProvider] = {}
        self._usage_specs: Dict[str, CredentialUsageSpec] = {}

        # Cache
        self._cache: Dict[str, tuple[CredentialObject, datetime]] = {}
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.RLock()

        self._auto_refresh = auto_refresh

        # Register providers
        for provider in (providers or [StaticProvider()]):
            self.register_provider(provider)

        # Template resolver
        self._resolver = TemplateResolver(self)

    def register_provider(self, provider: CredentialProvider) -> None:
        """Register a credential provider."""
        self._providers[provider.provider_id] = provider

    def register_usage(self, spec: CredentialUsageSpec) -> None:
        """Register how a tool uses credentials."""
        self._usage_specs[spec.credential_id] = spec

    # --- Credential Access ---

    def get_credential(
        self,
        credential_id: str,
        refresh_if_needed: bool = True
    ) -> Optional[CredentialObject]:
        """
        Get a credential by ID.

        Args:
            credential_id: The credential identifier
            refresh_if_needed: If True, refresh expired credentials

        Returns:
            CredentialObject or None if not found
        """
        with self._lock:
            # Check cache
            cached = self._get_from_cache(credential_id)
            if cached is not None:
                if refresh_if_needed and self._should_refresh(cached):
                    return self._refresh_credential(cached)
                return cached

            # Load from storage
            credential = self._storage.load(credential_id)
            if credential is None:
                return None

            # Refresh if needed
            if refresh_if_needed and self._should_refresh(credential):
                credential = self._refresh_credential(credential)

            # Cache
            self._add_to_cache(credential)

            return credential

    def get_key(self, credential_id: str, key_name: str) -> Optional[str]:
        """Convenience method to get a specific key value."""
        credential = self.get_credential(credential_id)
        if credential is None:
            return None
        return credential.get_key(key_name)

    def get(self, credential_id: str) -> Optional[str]:
        """
        Legacy compatibility: get the primary key value.

        For single-key credentials, returns that key.
        For multi-key, returns 'value', 'api_key', or 'access_token'.
        """
        credential = self.get_credential(credential_id)
        if credential is None:
            return None

        for key_name in ["value", "api_key", "access_token"]:
            if key_name in credential.keys:
                return credential.get_key(key_name)

        if credential.keys:
            first_key = next(iter(credential.keys))
            return credential.get_key(first_key)

        return None

    # --- Template Resolution ---

    def resolve(self, template: str) -> str:
        """Resolve credential templates in a string."""
        return self._resolver.resolve(template)

    def resolve_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Resolve credential templates in headers dictionary."""
        return self._resolver.resolve_headers(headers)

    def resolve_for_usage(self, credential_id: str) -> Dict[str, str]:
        """Get resolved headers for a registered usage spec."""
        spec = self._usage_specs.get(credential_id)
        if spec is None:
            raise ValueError(f"No usage spec registered for '{credential_id}'")
        return self.resolve_headers(spec.headers)

    # --- Credential Management ---

    def save_credential(self, credential: CredentialObject) -> None:
        """Save a credential to storage."""
        with self._lock:
            self._storage.save(credential)
            self._add_to_cache(credential)

    def delete_credential(self, credential_id: str) -> bool:
        """Delete a credential."""
        with self._lock:
            self._remove_from_cache(credential_id)
            return self._storage.delete(credential_id)

    def list_credentials(self) -> List[str]:
        """List all available credential IDs."""
        return self._storage.list_all()

    def is_available(self, credential_id: str) -> bool:
        """Check if a credential is available."""
        return self.get_credential(credential_id, refresh_if_needed=False) is not None

    # --- Validation ---

    def validate_for_usage(self, credential_id: str) -> List[str]:
        """
        Validate that a credential meets its usage spec requirements.

        Returns list of missing keys or empty list if valid.
        """
        spec = self._usage_specs.get(credential_id)
        if spec is None:
            return []

        credential = self.get_credential(credential_id)
        if credential is None:
            return [f"Credential '{credential_id}' not found"]

        missing = []
        for key_name in spec.required_keys:
            if key_name not in credential.keys:
                missing.append(key_name)

        return missing

    # --- Factory Methods ---

    @classmethod
    def for_testing(
        cls,
        credentials: Dict[str, Dict[str, str]]
    ) -> "CredentialStore":
        """
        Create a credential store for testing with mock credentials.

        Args:
            credentials: Dict mapping credential_id to {key_name: value}
                        e.g., {"brave_search": {"api_key": "test-key"}}

        Returns:
            CredentialStore with in-memory credentials
        """
        # ... implementation ...
```

---

## OAuth2 Module

**Location**: `core/framework/credentials/oauth2/`

### OAuth2Token

```python
@dataclass
class OAuth2Token:
    """Represents an OAuth2 token with metadata."""
    access_token: str
    token_type: str = "Bearer"
    expires_at: Optional[datetime] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 5-minute buffer)."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= (self.expires_at - timedelta(minutes=5))

    @property
    def can_refresh(self) -> bool:
        """Check if token can be refreshed."""
        return self.refresh_token is not None
```

### OAuth2Config

```python
@dataclass
class OAuth2Config:
    """Configuration for an OAuth2 provider."""
    token_url: str
    authorization_url: Optional[str] = None
    revocation_url: Optional[str] = None

    client_id: str = ""
    client_secret: str = ""
    default_scopes: list[str] = field(default_factory=list)

    # Token placement for requests (bipartisan model)
    token_placement: TokenPlacement = TokenPlacement.HEADER_BEARER
    custom_header_name: Optional[str] = None

    request_timeout: float = 30.0
    extra_token_params: dict[str, str] = field(default_factory=dict)


class TokenPlacement(Enum):
    """Where to place the access token in requests."""
    HEADER_BEARER = "header_bearer"   # Authorization: Bearer <token>
    HEADER_CUSTOM = "header_custom"    # Custom header name
    QUERY_PARAM = "query_param"       # ?access_token=<token>
```

### BaseOAuth2Provider

```python
class BaseOAuth2Provider(CredentialProvider):
    """
    Generic OAuth2 provider implementation.

    Works with standard OAuth2 servers. Override methods for
    provider-specific behavior.

    OSS users can extend this class for custom providers.
    """

    def __init__(self, config: OAuth2Config):
        self.config = config
        self._client = httpx.Client(timeout=config.request_timeout)

    def client_credentials_grant(
        self,
        scopes: Optional[list[str]] = None,
    ) -> OAuth2Token:
        """Obtain token using client credentials flow."""
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            **self.config.extra_token_params,
        }

        if scopes or self.config.default_scopes:
            data["scope"] = " ".join(scopes or self.config.default_scopes)

        return self._token_request(data)

    def refresh_token(
        self,
        refresh_token: str,
        scopes: Optional[list[str]] = None,
    ) -> OAuth2Token:
        """Refresh access token using refresh_token grant."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
            **self.config.extra_token_params,
        }

        if scopes:
            data["scope"] = " ".join(scopes)

        return self._token_request(data)

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """Implement CredentialProvider.refresh()."""
        refresh_tok = credential.get_key("refresh_token")
        if not refresh_tok:
            raise CredentialRefreshError(
                f"Credential '{credential.id}' has no refresh_token"
            )

        new_token = self.refresh_token(refresh_tok)

        credential.set_key(
            "access_token",
            new_token.access_token,
            expires_at=new_token.expires_at
        )

        if new_token.refresh_token:
            credential.set_key("refresh_token", new_token.refresh_token)

        credential.last_refreshed = datetime.utcnow()
        return credential

    def validate(self, credential: CredentialObject) -> bool:
        """Check if access_token exists and is not expired."""
        access_key = credential.keys.get("access_token")
        if access_key is None:
            return False
        return not access_key.is_expired

    def format_for_request(self, token: OAuth2Token) -> dict[str, Any]:
        """Format token for HTTP requests (bipartisan model)."""
        placement = self.config.token_placement

        if placement == TokenPlacement.HEADER_BEARER:
            return {
                "headers": {
                    "Authorization": f"{token.token_type} {token.access_token}"
                }
            }
        elif placement == TokenPlacement.HEADER_CUSTOM:
            return {
                "headers": {
                    self.config.custom_header_name: token.access_token
                }
            }
        elif placement == TokenPlacement.QUERY_PARAM:
            return {
                "params": {"access_token": token.access_token}
            }

        return {}

    # ... _token_request helper ...
```

### TokenLifecycleManager

```python
class TokenLifecycleManager:
    """
    Manages the complete lifecycle of OAuth2 tokens.

    Responsibilities:
    - Coordinate with CredentialStore for persistence
    - Automatically refresh expired tokens
    - Handle refresh failures gracefully
    """

    def __init__(
        self,
        provider: BaseOAuth2Provider,
        credential_name: str,
        store: CredentialStore,
        refresh_buffer_minutes: int = 5,
    ):
        self.provider = provider
        self.credential_name = credential_name
        self.store = store
        self.refresh_buffer = timedelta(minutes=refresh_buffer_minutes)
        self._cached_token: Optional[OAuth2Token] = None

    async def get_valid_token(self) -> Optional[OAuth2Token]:
        """Get a valid access token, refreshing if necessary."""
        credential = self.store.get_credential(self.credential_name)
        if credential is None:
            return None

        # Build OAuth2Token from credential
        token = self._credential_to_token(credential)

        if self._needs_refresh(token):
            token = await self._refresh_token(credential)

        return token

    async def acquire_token_client_credentials(
        self,
        scopes: Optional[list[str]] = None,
    ) -> OAuth2Token:
        """Acquire a new token using client credentials flow."""
        token = self.provider.client_credentials_grant(scopes=scopes)
        self._save_token_to_store(token)
        return token

    # ... helper methods ...
```

---

## HashiCorp Vault Integration

**Location**: `core/framework/credentials/vault/hashicorp.py`

HashiCorp Vault provides enterprise-grade secret management with:
- Dynamic secrets
- Lease management
- Audit logging
- Access policies

### HashiCorpVaultStorage

```python
class HashiCorpVaultStorage(CredentialStorage):
    """
    HashiCorp Vault storage adapter.

    Requires: pip install hvac

    Features:
    - KV v2 secrets engine support
    - Automatic lease renewal
    - Namespace support (Enterprise)

    Example:
        storage = HashiCorpVaultStorage(
            url="https://vault.example.com:8200",
            token="hvs.xxx",  # Or use VAULT_TOKEN env var
            mount_point="secret",
            path_prefix="hive/credentials"
        )

        store = CredentialStore(storage=storage)
    """

    def __init__(
        self,
        url: str,
        token: Optional[str] = None,
        mount_point: str = "secret",
        path_prefix: str = "hive/credentials",
        namespace: Optional[str] = None,
    ):
        """
        Initialize Vault storage.

        Args:
            url: Vault server URL (e.g., https://vault.example.com:8200)
            token: Vault token. If None, reads from VAULT_TOKEN env var
            mount_point: KV secrets engine mount point
            path_prefix: Path prefix for all credentials
            namespace: Vault namespace (Enterprise feature)
        """
        try:
            import hvac
        except ImportError:
            raise ImportError(
                "HashiCorp Vault support requires 'hvac'. "
                "Install with: pip install hvac"
            )

        import os

        self._url = url
        self._token = token or os.environ.get("VAULT_TOKEN")
        self._mount = mount_point
        self._prefix = path_prefix
        self._namespace = namespace

        self._client = hvac.Client(
            url=url,
            token=self._token,
            namespace=namespace
        )

        if not self._client.is_authenticated():
            raise ValueError(
                "Vault authentication failed. Check VAULT_TOKEN or token parameter."
            )

    def save(self, credential: CredentialObject) -> None:
        """Save credential to Vault KV v2."""
        path = self._path(credential.id)
        data = self._serialize_for_vault(credential)

        self._client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret=data,
            mount_point=self._mount
        )

    def load(self, credential_id: str) -> Optional[CredentialObject]:
        """Load credential from Vault."""
        path = self._path(credential_id)

        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount
            )
            data = response["data"]["data"]
            return self._deserialize_from_vault(credential_id, data)
        except Exception as e:
            logger.debug(f"Credential not found at {path}: {e}")
            return None

    def delete(self, credential_id: str) -> bool:
        """Delete credential from Vault."""
        path = self._path(credential_id)
        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=self._mount
            )
            return True
        except Exception:
            return False

    def list_all(self) -> List[str]:
        """List all credentials under the prefix."""
        try:
            response = self._client.secrets.kv.v2.list_secrets(
                path=self._prefix,
                mount_point=self._mount
            )
            return response["data"]["keys"]
        except Exception:
            return []

    def exists(self, credential_id: str) -> bool:
        return self.load(credential_id) is not None

    def _path(self, credential_id: str) -> str:
        """Build Vault path for credential."""
        return f"{self._prefix}/{credential_id}"

    def _serialize_for_vault(self, credential: CredentialObject) -> dict:
        """Convert credential to Vault secret format."""
        data = {"_type": credential.credential_type.value}

        for key_name, key in credential.keys.items():
            data[key_name] = key.get_secret_value()
            if key.expires_at:
                data[f"_expires_{key_name}"] = key.expires_at.isoformat()

        if credential.provider_id:
            data["_provider_id"] = credential.provider_id

        return data

    def _deserialize_from_vault(
        self,
        credential_id: str,
        data: dict
    ) -> CredentialObject:
        """Reconstruct credential from Vault secret."""
        cred_type = CredentialType(data.pop("_type", "api_key"))
        provider_id = data.pop("_provider_id", None)

        keys = {}
        for key, value in list(data.items()):
            if key.startswith("_"):
                continue

            expires_at = None
            expires_key = f"_expires_{key}"
            if expires_key in data:
                expires_at = datetime.fromisoformat(data[expires_key])

            keys[key] = CredentialKey(
                name=key,
                value=SecretStr(value),
                expires_at=expires_at
            )

        return CredentialObject(
            id=credential_id,
            credential_type=cred_type,
            keys=keys,
            provider_id=provider_id
        )
```

### Vault Configuration Example

```python
# Example: Setting up HashiCorp Vault integration

from framework.credentials.store import CredentialStore
from framework.credentials.vault.hashicorp import HashiCorpVaultStorage
from framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config

# 1. Configure Vault storage
vault_storage = HashiCorpVaultStorage(
    url="https://vault.mycompany.com:8200",
    # token read from VAULT_TOKEN env var
    mount_point="secret",
    path_prefix="hive/agents/prod"
)

# 2. Configure OAuth2 provider
github_oauth = BaseOAuth2Provider(OAuth2Config(
    token_url="https://github.com/login/oauth/access_token",
    client_id="your-client-id",
    client_secret="your-client-secret",  # Or fetch from Vault
))

# 3. Create credential store
store = CredentialStore(
    storage=vault_storage,
    providers=[github_oauth]
)

# 4. Use credentials
headers = store.resolve_headers({
    "Authorization": "Bearer {{github_oauth.access_token}}"
})
```

---

## Backward Compatibility

**Location**: `tools/src/aden_tools/credentials/store_adapter.py`

### CredentialStoreAdapter

```python
class CredentialStoreAdapter(CredentialManager):
    """
    Adapter that makes CredentialStore compatible with existing CredentialManager API.

    This allows gradual migration: existing tools continue to work while
    new features are available.

    Usage:
        from framework.credentials.store import CredentialStore
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        store = CredentialStore(...)
        credentials = CredentialStoreAdapter(store)

        # Existing API works unchanged
        api_key = credentials.get("brave_search")
        credentials.validate_for_tools(["web_search"])

        # New features also available
        headers = credentials.resolve_headers({
            "Authorization": "Bearer {{github_oauth.access_token}}"
        })
    """

    def __init__(
        self,
        store: CredentialStore,
        specs: Optional[Dict[str, CredentialSpec]] = None,
    ):
        # Note: Don't call parent __init__ - we're replacing its behavior
        if specs is None:
            from . import CREDENTIAL_SPECS
            specs = CREDENTIAL_SPECS

        self._store = store
        self._specs = specs

        # Build tool -> credential mapping
        self._tool_to_cred: Dict[str, str] = {}
        for cred_name, spec in self._specs.items():
            for tool_name in spec.tools:
                self._tool_to_cred[tool_name] = cred_name

    def get(self, name: str) -> Optional[str]:
        """Get credential value using the new store."""
        return self._store.get(name)

    def is_available(self, name: str) -> bool:
        """Check if credential is available."""
        return self._store.is_available(name)

    def validate_for_tools(self, tool_names: List[str]) -> None:
        """Validate credentials for tools."""
        missing = self.get_missing_for_tools(tool_names)
        if missing:
            raise CredentialError(self._format_missing_error(missing, tool_names))

    # --- New Methods ---

    def resolve_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Resolve credential templates in headers."""
        return self._store.resolve_headers(headers)

    def get_key(self, credential_id: str, key_name: str) -> Optional[str]:
        """Get a specific key from a multi-key credential."""
        return self._store.get_key(credential_id, key_name)

    @property
    def store(self) -> CredentialStore:
        """Access the underlying credential store."""
        return self._store
```

---

## Usage Examples

### Example 1: Simple API Key (Backward Compatible)

```python
# Existing code continues to work without changes
from aden_tools.credentials import CredentialManager

credentials = CredentialManager()
api_key = credentials.get("brave_search")

# Tool uses it directly
response = httpx.get(
    "https://api.search.brave.com/res/v1/web/search",
    headers={"X-Subscription-Token": api_key}
)
```

### Example 2: Multi-Key Credential with Templates

```python
from framework.credentials.store import CredentialStore
from framework.credentials.storage import EncryptedFileStorage

# Create store with encrypted storage
store = CredentialStore(
    storage=EncryptedFileStorage("/var/hive/credentials")
)

# Tool specifies how to use credentials (bipartisan model)
headers = store.resolve_headers({
    "Authorization": "Bearer {{github_oauth.access_token}}",
    "X-API-Key": "{{brave_search.api_key}}"
})

response = httpx.get("https://api.example.com", headers=headers)
```

### Example 3: OAuth2 with Auto-Refresh

```python
from framework.credentials.store import CredentialStore
from framework.credentials.oauth2 import BaseOAuth2Provider, OAuth2Config

# Configure OAuth2 provider
provider = BaseOAuth2Provider(OAuth2Config(
    token_url="https://accounts.google.com/o/oauth2/token",
    client_id="your-client-id",
    client_secret="your-client-secret",
    default_scopes=["https://www.googleapis.com/auth/drive.readonly"]
))

store = CredentialStore(providers=[provider])

# Save OAuth2 credential
from framework.credentials.models import CredentialObject, CredentialKey, CredentialType
from pydantic import SecretStr

store.save_credential(CredentialObject(
    id="google_drive",
    credential_type=CredentialType.OAUTH2,
    keys={
        "access_token": CredentialKey(
            name="access_token",
            value=SecretStr("ya29.xxx"),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        ),
        "refresh_token": CredentialKey(
            name="refresh_token",
            value=SecretStr("1//xxx")
        )
    },
    provider_id="oauth2",
    auto_refresh=True
))

# Token auto-refreshes when expired
token = store.get_key("google_drive", "access_token")
```

### Example 4: Custom Provider (OSS Extensibility)

```python
from framework.credentials.provider import CredentialProvider, CredentialRefreshError
from framework.credentials.models import CredentialObject, CredentialType

class MyCustomProvider(CredentialProvider):
    """Provider for my custom auth system."""

    @property
    def provider_id(self) -> str:
        return "my_custom_auth"

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.CUSTOM]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        # Custom refresh logic
        api_key = credential.get_key("api_key")

        # Call your auth API
        response = requests.post(
            "https://auth.myservice.com/refresh",
            headers={"X-API-Key": api_key}
        )
        data = response.json()

        credential.set_key(
            "access_token",
            data["token"],
            expires_at=datetime.fromisoformat(data["expires_at"])
        )
        return credential

    def validate(self, credential: CredentialObject) -> bool:
        token = credential.get_key("access_token")
        response = requests.get(
            "https://auth.myservice.com/validate",
            headers={"Authorization": f"Bearer {token}"}
        )
        return response.status_code == 200

# Register with store
store.register_provider(MyCustomProvider())
```

### Example 5: HashiCorp Vault in Production

```python
from framework.credentials.store import CredentialStore
from framework.credentials.vault.hashicorp import HashiCorpVaultStorage

# Production setup with Vault
storage = HashiCorpVaultStorage(
    url="https://vault.prod.mycompany.com:8200",
    mount_point="secret",
    path_prefix="hive/agents/production",
    namespace="team-ai"  # Enterprise namespace
)

store = CredentialStore(storage=storage)

# Credentials are stored/retrieved from Vault
api_key = store.get("openai")
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Days 1-2)

| File | Description |
|------|-------------|
| `core/framework/credentials/__init__.py` | Public exports |
| `core/framework/credentials/models.py` | CredentialObject, CredentialKey, CredentialUsageSpec |
| `core/framework/credentials/template.py` | TemplateResolver for {{cred.key}} patterns |
| `core/framework/credentials/storage.py` | CredentialStorage ABC, EncryptedFileStorage, EnvVarStorage |
| `core/framework/credentials/provider.py` | CredentialProvider ABC, StaticProvider |

### Phase 2: Main Store (Days 2-3)

| File | Description |
|------|-------------|
| `core/framework/credentials/store.py` | CredentialStore orchestrator |
| `tools/src/aden_tools/credentials/store_adapter.py` | Backward compatibility adapter |

### Phase 3: OAuth2 Support (Days 3-4)

| File | Description |
|------|-------------|
| `core/framework/credentials/oauth2/__init__.py` | OAuth2 module exports |
| `core/framework/credentials/oauth2/provider.py` | OAuth2Token, OAuth2Config, TokenPlacement |
| `core/framework/credentials/oauth2/base_provider.py` | BaseOAuth2Provider |
| `core/framework/credentials/oauth2/lifecycle.py` | TokenLifecycleManager |

### Phase 4: Vault Integration (Days 4-5)

| File | Description |
|------|-------------|
| `core/framework/credentials/vault/__init__.py` | Vault module exports |
| `core/framework/credentials/vault/hashicorp.py` | HashiCorpVaultStorage |

### Phase 5: Integration & Testing (Days 5-6)

| Task | Description |
|------|-------------|
| Update `tools/mcp_server.py` | Integrate new CredentialStore |
| Update tool registrations | Migrate to template-based usage |
| Comprehensive test suite | Unit and integration tests |
| Documentation | Update README, add examples |

---

## Security Considerations

### Encryption

1. **At-Rest Encryption**: EncryptedFileStorage uses Fernet (AES-128-CBC + HMAC)
2. **Master Key**: Read from `HIVE_CREDENTIAL_KEY` environment variable
3. **Key Generation**: Fernet.generate_key() for new installations

### Secret Handling

1. **SecretStr**: Pydantic's SecretStr prevents accidental logging
2. **Memory**: Secrets cleared from cache after TTL expires
3. **Transmission**: Never logged or printed in errors

### Thread Safety

1. **RLock**: All store operations protected by reentrant lock
2. **Cache**: Thread-safe read/write with TTL expiration

### Vault Security

1. **Authentication**: Token-based auth, supports VAULT_TOKEN env var
2. **Namespaces**: Enterprise namespace support for isolation
3. **Audit**: Vault provides comprehensive audit logging

---

## File Structure Summary

```
core/framework/credentials/
├── __init__.py           # Public exports
├── models.py             # CredentialObject, CredentialKey, CredentialUsageSpec
├── store.py              # CredentialStore (main orchestrator)
├── storage.py            # CredentialStorage ABC + EncryptedFileStorage, EnvVarStorage
├── provider.py           # CredentialProvider ABC + StaticProvider
├── template.py           # TemplateResolver for {{cred.key}}
├── oauth2/
│   ├── __init__.py
│   ├── provider.py       # OAuth2Token, OAuth2Config, TokenPlacement
│   ├── base_provider.py  # BaseOAuth2Provider
│   └── lifecycle.py      # TokenLifecycleManager
└── vault/
    ├── __init__.py
    └── hashicorp.py      # HashiCorpVaultStorage

tools/src/aden_tools/credentials/
├── (existing files)
└── store_adapter.py      # CredentialStoreAdapter for backward compat
```

---

## Verification Plan

### Unit Tests

- [ ] CredentialObject CRUD operations
- [ ] TemplateResolver with various patterns
- [ ] EncryptedFileStorage encryption/decryption
- [ ] EnvVarStorage hot-reload
- [ ] StaticProvider validation
- [ ] OAuth2 token refresh flow
- [ ] HashiCorpVaultStorage operations (mocked)

### Integration Tests

- [ ] End-to-end credential flow
- [ ] Template resolution in HTTP headers
- [ ] OAuth2 auto-refresh with lifecycle manager
- [ ] Backward compatibility with existing tools

### Manual Testing

- [ ] Create encrypted credential store
- [ ] Save and load multi-key credentials
- [ ] Verify template resolution in tool headers
- [ ] Test OAuth2 token refresh
- [ ] Verify existing tools continue working
- [ ] Test Vault integration (if Vault available)
