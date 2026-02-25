"""
Aden Credential Client.

HTTP client for the Aden authentication server.
Aden holds all OAuth secrets; agents receive only short-lived access tokens.

API (all endpoints authenticated with Bearer {api_key}):

    GET  /v1/credentials                          — list integrations
    GET  /v1/credentials/{integration_id}          — get access token (auto-refreshes)
    POST /v1/credentials/{integration_id}/refresh  — force refresh
    GET  /v1/credentials/{integration_id}/validate — check validity

Integration IDs are base64-encoded hashes assigned by the Aden platform
(e.g. "Z29vZ2xlOlRpbW90aHk6MTYwNjc6MTM2ODQ"), NOT provider names.

Usage:
    client = AdenCredentialClient(AdenClientConfig(
        base_url="https://api.adenhq.com",
    ))

    # List what's connected
    for info in client.list_integrations():
        print(f"{info.provider}/{info.alias}: {info.status}")

    # Get an access token
    cred = client.get_credential(info.integration_id)
    print(cred.access_token)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AdenClientError(Exception):
    """Base exception for Aden client errors."""

    pass


class AdenAuthenticationError(AdenClientError):
    """Raised when API key is invalid or revoked."""

    pass


class AdenNotFoundError(AdenClientError):
    """Raised when integration is not found."""

    pass


class AdenRefreshError(AdenClientError):
    """Raised when token refresh fails."""

    def __init__(
        self,
        message: str,
        requires_reauthorization: bool = False,
        reauthorization_url: str | None = None,
    ):
        super().__init__(message)
        self.requires_reauthorization = requires_reauthorization
        self.reauthorization_url = reauthorization_url


class AdenRateLimitError(AdenClientError):
    """Raised when rate limited."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class AdenClientConfig:
    """Configuration for Aden API client."""

    base_url: str
    """Base URL of the Aden server (e.g., 'https://api.adenhq.com')."""

    api_key: str | None = None
    """Agent API key. Loaded from ADEN_API_KEY env var if not provided."""

    tenant_id: str | None = None
    """Optional tenant ID for multi-tenant deployments."""

    timeout: float = 30.0
    """Request timeout in seconds."""

    retry_attempts: int = 3
    """Number of retry attempts for transient failures."""

    retry_delay: float = 1.0
    """Base delay between retries in seconds (exponential backoff)."""

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("ADEN_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "Aden API key not provided. Either pass api_key to AdenClientConfig "
                    "or set the ADEN_API_KEY environment variable."
                )


@dataclass
class AdenIntegrationInfo:
    """An integration from GET /v1/credentials.

    Example response item::

        {
            "integration_id": "Z29vZ2xlOlRpbW90aHk6MTYwNjc6MTM2ODQ",
            "provider": "google",
            "alias": "Timothy",
            "status": "active",
            "email": "timothy@acho.io",
            "expires_at": "2026-02-20T21:46:04.863Z"
        }
    """

    integration_id: str
    """Base64-encoded hash ID assigned by Aden."""

    provider: str
    """Provider type (e.g. "google", "slack", "hubspot")."""

    alias: str
    """User-set alias on the Aden platform."""

    status: str
    """Status: "active", "expired", "requires_reauth"."""

    email: str = ""
    """Email associated with this connection."""

    expires_at: datetime | None = None
    """When the current access token expires."""

    # Backward compat — old code reads integration_type
    @property
    def integration_type(self) -> str:
        return self.provider

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdenIntegrationInfo:
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        return cls(
            integration_id=data.get("integration_id", ""),
            provider=data.get("provider", ""),
            alias=data.get("alias", ""),
            status=data.get("status", "unknown"),
            email=data.get("email", ""),
            expires_at=expires_at,
        )


@dataclass
class AdenCredentialResponse:
    """Response from GET /v1/credentials/{integration_id}.

    Example::

        {
            "access_token": "ya29.a0AfH6SM...",
            "token_type": "Bearer",
            "expires_at": "2026-02-20T12:00:00.000Z",
            "provider": "google",
            "alias": "Timothy",
            "email": "timothy@acho.io"
        }
    """

    integration_id: str
    """The integration_id used in the request."""

    access_token: str
    """Short-lived access token for API calls."""

    token_type: str = "Bearer"

    expires_at: datetime | None = None

    provider: str = ""
    """Provider type (e.g. "google")."""

    alias: str = ""
    """User-set alias."""

    email: str = ""
    """Email associated with this connection."""

    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Backward compat
    @property
    def integration_type(self) -> str:
        return self.provider

    @classmethod
    def from_dict(cls, data: dict[str, Any], integration_id: str = "") -> AdenCredentialResponse:
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        # Build metadata from email if present
        metadata = data.get("metadata") or {}
        if not metadata and data.get("email"):
            metadata = {"email": data["email"]}

        return cls(
            integration_id=integration_id or data.get("integration_id", ""),
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            provider=data.get("provider", ""),
            alias=data.get("alias", ""),
            email=data.get("email", ""),
            scopes=data.get("scopes", []),
            metadata=metadata,
        )


class AdenCredentialClient:
    """
    HTTP client for Aden credential server.

    Usage:
        client = AdenCredentialClient(AdenClientConfig(
            base_url="https://api.adenhq.com",
        ))

        # List integrations
        for info in client.list_integrations():
            print(f"{info.provider}/{info.alias}: {info.status}")

        # Get access token (uses base64 integration_id, NOT provider name)
        cred = client.get_credential(info.integration_id)
        headers = {"Authorization": f"Bearer {cred.access_token}"}

        client.close()
    """

    def __init__(self, config: AdenClientConfig):
        self.config = config
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "hive-credential-store/1.0",
            }
            if self.config.tenant_id:
                headers["X-Tenant-ID"] = self.config.tenant_id

            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers=headers,
            )
        return self._client

    def _request_with_retry(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a request with retry logic."""
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.config.retry_attempts):
            try:
                response = client.request(method, path, **kwargs)

                if response.status_code == 401:
                    raise AdenAuthenticationError("Agent API key is invalid or revoked")

                if response.status_code == 403:
                    data = response.json()
                    raise AdenClientError(data.get("message", "Forbidden"))

                if response.status_code == 404:
                    raise AdenNotFoundError(f"Integration not found: {path}")

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise AdenRateLimitError(
                        "Rate limited by Aden server",
                        retry_after=retry_after,
                    )

                if response.status_code == 400:
                    data = response.json()
                    msg = data.get("message", "Bad request")
                    if data.get("error") == "refresh_failed" or "refresh" in msg.lower():
                        raise AdenRefreshError(
                            msg,
                            requires_reauthorization=data.get("requires_reauthorization", False),
                            reauthorization_url=data.get("reauthorization_url"),
                        )
                    raise AdenClientError(f"Bad request: {msg}")

                response.raise_for_status()
                return response

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.config.retry_attempts - 1:
                    delay = self.config.retry_delay * (2**attempt)
                    logger.warning(
                        f"Aden request failed (attempt {attempt + 1}), retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    raise AdenClientError(f"Failed to connect to Aden server: {e}") from e

            except (
                AdenAuthenticationError,
                AdenNotFoundError,
                AdenRefreshError,
                AdenRateLimitError,
            ):
                raise

        raise AdenClientError(
            f"Request failed after {self.config.retry_attempts} attempts"
        ) from last_error

    def list_integrations(self) -> list[AdenIntegrationInfo]:
        """
        List all integrations for this agent's team.

        GET /v1/credentials → {"integrations": [...]}

        Returns:
            List of AdenIntegrationInfo with integration_id, provider,
            alias, status, email, expires_at.
        """
        response = self._request_with_retry("GET", "/v1/credentials")
        data = response.json()
        return [AdenIntegrationInfo.from_dict(item) for item in data.get("integrations", [])]

    # Alias
    list_connections = list_integrations

    def get_credential(self, integration_id: str) -> AdenCredentialResponse | None:
        """
        Get access token for an integration. Auto-refreshes if near expiry.

        GET /v1/credentials/{integration_id}

        Args:
            integration_id: Base64 hash ID from list_integrations().

        Returns:
            AdenCredentialResponse with access_token, or None if not found.
        """
        try:
            response = self._request_with_retry("GET", f"/v1/credentials/{integration_id}")
            data = response.json()
            return AdenCredentialResponse.from_dict(data, integration_id=integration_id)
        except AdenNotFoundError:
            return None

    def request_refresh(self, integration_id: str) -> AdenCredentialResponse:
        """
        Force refresh the access token.

        POST /v1/credentials/{integration_id}/refresh

        Args:
            integration_id: Base64 hash ID.

        Returns:
            AdenCredentialResponse with new access_token.
        """
        response = self._request_with_retry("POST", f"/v1/credentials/{integration_id}/refresh")
        data = response.json()
        return AdenCredentialResponse.from_dict(data, integration_id=integration_id)

    def validate_token(self, integration_id: str) -> dict[str, Any]:
        """
        Check if an integration's OAuth connection is valid.

        GET /v1/credentials/{integration_id}/validate

        Returns:
            {"valid": bool, "status": str, "expires_at": str, "error": str|null}
        """
        response = self._request_with_retry("GET", f"/v1/credentials/{integration_id}/validate")
        return response.json()

    def health_check(self) -> dict[str, Any]:
        """Check Aden server health."""
        try:
            client = self._get_client()
            response = client.get("/health")
            if response.status_code == 200:
                data = response.json()
                data["latency_ms"] = response.elapsed.total_seconds() * 1000
                return data
            return {"status": "degraded", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> AdenCredentialClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
