"""
Core data models for the credential store.

This module defines the key-vault structure where credentials are objects
containing one or more keys (e.g., api_key, access_token, refresh_token).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


class CredentialType(str, Enum):
    """Types of credentials the store can manage."""

    API_KEY = "api_key"
    """Simple API key (e.g., Brave Search, OpenAI)"""

    OAUTH2 = "oauth2"
    """OAuth2 with refresh token support"""

    BASIC_AUTH = "basic_auth"
    """Username/password pair"""

    BEARER_TOKEN = "bearer_token"
    """JWT or bearer token without refresh"""

    CUSTOM = "custom"
    """User-defined credential type"""


class CredentialKey(BaseModel):
    """
    A single key within a credential object.

    Example: 'api_key' within a 'brave_search' credential

    Attributes:
        name: Key name (e.g., 'api_key', 'access_token')
        value: Secret value (SecretStr prevents accidental logging)
        expires_at: Optional expiration time
        metadata: Additional key-specific metadata
    """

    name: str
    value: SecretStr
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    @property
    def is_expired(self) -> bool:
        """Check if this key has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def get_secret_value(self) -> str:
        """Get the actual secret value (use sparingly)."""
        return self.value.get_secret_value()


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
                "access_token": CredentialKey(name="access_token", value=SecretStr("ghp_xxx")),
                "refresh_token": CredentialKey(name="refresh_token", value=SecretStr("ghr_xxx")),
            },
            provider_id="oauth2"
        )

    Attributes:
        id: Unique identifier (e.g., 'brave_search', 'github_oauth')
        credential_type: Type of credential (API_KEY, OAUTH2, etc.)
        keys: Dictionary of key name to CredentialKey
        provider_id: ID of provider responsible for lifecycle management
        auto_refresh: Whether to automatically refresh when expired
    """

    id: str = Field(description="Unique identifier (e.g., 'brave_search', 'github_oauth')")
    credential_type: CredentialType = CredentialType.API_KEY
    keys: dict[str, CredentialKey] = Field(default_factory=dict)

    # Lifecycle management
    provider_id: str | None = Field(
        default=None,
        description="ID of provider responsible for lifecycle (e.g., 'oauth2', 'static')",
    )
    last_refreshed: datetime | None = None
    auto_refresh: bool = False

    # Usage tracking
    last_used: datetime | None = None
    use_count: int = 0

    # Metadata
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "allow"}

    def get_key(self, key_name: str) -> str | None:
        """
        Get a specific key's value.

        Args:
            key_name: Name of the key to retrieve

        Returns:
            The key's secret value, or None if not found
        """
        key = self.keys.get(key_name)
        if key is None:
            return None
        return key.get_secret_value()

    def set_key(
        self,
        key_name: str,
        value: str,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Set or update a key.

        Args:
            key_name: Name of the key
            value: Secret value
            expires_at: Optional expiration time
            metadata: Optional key-specific metadata
        """
        self.keys[key_name] = CredentialKey(
            name=key_name,
            value=SecretStr(value),
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self.updated_at = datetime.now(UTC)

    def has_key(self, key_name: str) -> bool:
        """Check if a key exists."""
        return key_name in self.keys

    @property
    def needs_refresh(self) -> bool:
        """Check if any key is expired or near expiration."""
        for key in self.keys.values():
            if key.is_expired:
                return True
        return False

    @property
    def is_valid(self) -> bool:
        """Check if credential has at least one non-expired key."""
        if not self.keys:
            return False
        return not all(key.is_expired for key in self.keys.values())

    def record_usage(self) -> None:
        """Record that this credential was used."""
        self.last_used = datetime.now(UTC)
        self.use_count += 1

    def get_default_key(self) -> str | None:
        """
        Get the default key value.

        Priority: 'value' > 'api_key' > 'access_token' > first key

        Returns:
            The default key's value, or None if no keys exist
        """
        for key_name in ["value", "api_key", "access_token"]:
            if key_name in self.keys:
                return self.get_key(key_name)

        if self.keys:
            first_key = next(iter(self.keys))
            return self.get_key(first_key)

        return None


class CredentialUsageSpec(BaseModel):
    """
    Specification for how a tool uses credentials.

    This implements the "bipartisan" model where the credential store
    just stores values, and tools define how those values are used
    in HTTP requests (headers, query params, body).

    Example:
        CredentialUsageSpec(
            credential_id="brave_search",
            required_keys=["api_key"],
            headers={"X-Subscription-Token": "{{api_key}}"}
        )

        CredentialUsageSpec(
            credential_id="github_oauth",
            required_keys=["access_token"],
            headers={"Authorization": "Bearer {{access_token}}"}
        )

    Attributes:
        credential_id: ID of credential to use
        required_keys: Keys that must be present
        headers: Header templates with {{key}} placeholders
        query_params: Query parameter templates
        body_fields: Request body field templates
    """

    credential_id: str = Field(description="ID of credential to use (e.g., 'brave_search')")
    required_keys: list[str] = Field(default_factory=list, description="Keys that must be present")

    # Injection templates (bipartisan model)
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Header templates (e.g., {'Authorization': 'Bearer {{access_token}}'})",
    )
    query_params: dict[str, str] = Field(
        default_factory=dict,
        description="Query param templates (e.g., {'api_key': '{{api_key}}'})",
    )
    body_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Request body field templates",
    )

    # Metadata
    required: bool = True
    description: str = ""
    help_url: str = ""

    model_config = {"extra": "allow"}


class CredentialError(Exception):
    """Base exception for credential-related errors."""

    pass


class CredentialNotFoundError(CredentialError):
    """Raised when a referenced credential doesn't exist."""

    pass


class CredentialKeyNotFoundError(CredentialError):
    """Raised when a referenced key doesn't exist in a credential."""

    pass


class CredentialRefreshError(CredentialError):
    """Raised when credential refresh fails."""

    pass


class CredentialValidationError(CredentialError):
    """Raised when credential validation fails."""

    pass


class CredentialDecryptionError(CredentialError):
    """Raised when credential decryption fails."""

    pass
