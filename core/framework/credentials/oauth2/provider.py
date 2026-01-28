"""
OAuth2 types and configuration.

This module defines the core OAuth2 data structures:
- OAuth2Token: Represents an access token with metadata
- OAuth2Config: Configuration for OAuth2 endpoints
- TokenPlacement: Where to place tokens in requests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any


class TokenPlacement(str, Enum):
    """Where to place the access token in HTTP requests."""

    HEADER_BEARER = "header_bearer"
    """Authorization: Bearer <token> (most common)"""

    HEADER_CUSTOM = "header_custom"
    """Custom header name (e.g., X-Access-Token)"""

    QUERY_PARAM = "query_param"
    """Query parameter (e.g., ?access_token=<token>)"""

    BODY_PARAM = "body_param"
    """Form body parameter"""


@dataclass
class OAuth2Token:
    """
    Represents an OAuth2 token with metadata.

    Attributes:
        access_token: The access token string
        token_type: Token type (usually "Bearer")
        expires_at: When the token expires
        refresh_token: Optional refresh token
        scope: Granted scopes (space-separated)
        raw_response: Original token response from server
    """

    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    refresh_token: str | None = None
    scope: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """
        Check if token is expired.

        Uses a 5-minute buffer to account for clock skew and
        request latency.
        """
        if self.expires_at is None:
            return False
        buffer = timedelta(minutes=5)
        return datetime.now(UTC) >= (self.expires_at - buffer)

    @property
    def can_refresh(self) -> bool:
        """Check if token can be refreshed (has refresh_token)."""
        return self.refresh_token is not None and self.refresh_token.strip() != ""

    @property
    def expires_in_seconds(self) -> int | None:
        """Get seconds until expiration, or None if no expiration."""
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(UTC)
        return max(0, int(delta.total_seconds()))

    @classmethod
    def from_token_response(cls, data: dict[str, Any]) -> OAuth2Token:
        """
        Create OAuth2Token from an OAuth2 token endpoint response.

        Args:
            data: Token response JSON (access_token, token_type, expires_in, etc.)

        Returns:
            OAuth2Token instance
        """
        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
            raw_response=data,
        )


@dataclass
class OAuth2Config:
    """
    Configuration for an OAuth2 provider.

    This contains all the information needed to perform OAuth2 operations
    for a specific provider (GitHub, Google, Salesforce, etc.).

    Attributes:
        token_url: URL for token endpoint (required)
        authorization_url: URL for authorization endpoint (optional, for auth code flow)
        revocation_url: URL for token revocation (optional)
        introspection_url: URL for token introspection (optional)
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        default_scopes: Default scopes to request
        token_placement: How to include token in requests
        custom_header_name: Header name when using HEADER_CUSTOM placement
        query_param_name: Query param name when using QUERY_PARAM placement
        extra_token_params: Additional parameters for token requests
        request_timeout: Timeout for HTTP requests in seconds

    Example:
        config = OAuth2Config(
            token_url="https://github.com/login/oauth/access_token",
            authorization_url="https://github.com/login/oauth/authorize",
            client_id="your-client-id",
            client_secret="your-client-secret",
            default_scopes=["repo", "user"],
        )
    """

    # Endpoints (only token_url is strictly required)
    token_url: str
    authorization_url: str | None = None
    revocation_url: str | None = None
    introspection_url: str | None = None

    # Client credentials
    client_id: str = ""
    client_secret: str = ""

    # Scopes
    default_scopes: list[str] = field(default_factory=list)

    # Token placement for API calls (bipartisan model)
    token_placement: TokenPlacement = TokenPlacement.HEADER_BEARER
    custom_header_name: str | None = None
    query_param_name: str = "access_token"

    # Request configuration
    extra_token_params: dict[str, str] = field(default_factory=dict)
    request_timeout: float = 30.0

    # Additional headers for token requests
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.token_url:
            raise ValueError("token_url is required")

        if self.token_placement == TokenPlacement.HEADER_CUSTOM and not self.custom_header_name:
            raise ValueError("custom_header_name is required when using HEADER_CUSTOM placement")


class OAuth2Error(Exception):
    """
    OAuth2 protocol error.

    Attributes:
        error: OAuth2 error code (e.g., 'invalid_grant', 'invalid_client')
        description: Human-readable error description
        status_code: HTTP status code from the response
    """

    def __init__(
        self,
        error: str,
        description: str = "",
        status_code: int = 0,
    ):
        self.error = error
        self.description = description
        self.status_code = status_code
        super().__init__(f"{error}: {description}" if description else error)


class TokenExpiredError(OAuth2Error):
    """Raised when a token has expired and cannot be used."""

    def __init__(self, credential_id: str):
        super().__init__(
            error="token_expired",
            description=f"Token for '{credential_id}' has expired",
        )
        self.credential_id = credential_id


class RefreshTokenInvalidError(OAuth2Error):
    """Raised when the refresh token is invalid or revoked."""

    def __init__(self, credential_id: str, reason: str = ""):
        description = f"Refresh token for '{credential_id}' is invalid"
        if reason:
            description += f": {reason}"
        super().__init__(error="invalid_grant", description=description)
        self.credential_id = credential_id
