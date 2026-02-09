"""
Aden Credential Client.

HTTP client for communicating with the Aden authentication server.
The Aden server handles OAuth2 authorization flows and token management.
This client fetches tokens and delegates refresh operations to Aden.

Usage:
    # API key loaded from ADEN_API_KEY environment variable by default
    client = AdenCredentialClient(AdenClientConfig(
        base_url="https://api.adenhq.com",
    ))

    # Or explicitly provide the API key
    client = AdenCredentialClient(AdenClientConfig(
        base_url="https://api.adenhq.com",
        api_key="your-api-key",
    ))

    # Fetch a credential
    response = client.get_credential("hubspot")
    if response:
        print(f"Token expires at: {response.expires_at}")

    # Request a refresh
    refreshed = client.request_refresh("hubspot")
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
    """Agent's API key for authenticating with Aden.
    If not provided, loaded from ADEN_API_KEY environment variable."""

    tenant_id: str | None = None
    """Optional tenant ID for multi-tenant deployments."""

    timeout: float = 30.0
    """Request timeout in seconds."""

    retry_attempts: int = 3
    """Number of retry attempts for transient failures."""

    retry_delay: float = 1.0
    """Base delay between retries in seconds (exponential backoff)."""

    def __post_init__(self) -> None:
        """Load API key from environment if not provided."""
        if self.api_key is None:
            self.api_key = os.environ.get("ADEN_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "Aden API key not provided. Either pass api_key to AdenClientConfig "
                    "or set the ADEN_API_KEY environment variable."
                )


@dataclass
class AdenCredentialResponse:
    """Response from Aden server containing credential data."""

    integration_id: str
    """Unique identifier for the integration (e.g., 'hubspot')."""

    integration_type: str
    """Type of integration (e.g., 'hubspot', 'github', 'slack')."""

    access_token: str
    """The access token for API calls."""

    token_type: str = "Bearer"
    """Token type (usually 'Bearer')."""

    expires_at: datetime | None = None
    """When the access token expires (UTC)."""

    scopes: list[str] = field(default_factory=list)
    """OAuth2 scopes granted to this token."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional integration-specific metadata."""

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], integration_id: str | None = None
    ) -> AdenCredentialResponse:
        """Create from API response dictionary or normalized credential dict."""

        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        resolved_integration_id = (
            integration_id
            or data.get("integration_id")
            or data.get("alias")
            or data.get("provider", "")
        )

        resolved_integration_type = data.get("integration_type") or data.get("provider", "")
        metadata = data.get("metadata")
        if metadata is None and data.get("email"):
            metadata = {"email": data.get("email")}
        if metadata is None:
            metadata = {}

        return cls(
            integration_id=resolved_integration_id,
            integration_type=resolved_integration_type,
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scopes=data.get("scopes", []),
            metadata=metadata,
        )


@dataclass
class AdenIntegrationInfo:
    """Information about an available integration."""

    integration_id: str
    integration_type: str
    status: str  # "active", "requires_reauth", "expired"
    expires_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdenIntegrationInfo:
        """Create from API response dictionary."""
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        return cls(
            integration_id=data["integration_id"],
            integration_type=data.get("provider", data["integration_id"]),
            status=data.get("status", "unknown"),
            expires_at=expires_at,
        )


class AdenCredentialClient:
    """
    HTTP client for Aden credential server.

    Handles communication with the Aden authentication server,
    including fetching credentials, requesting refreshes, and
    reporting usage statistics.

    The client automatically handles:
    - Retries with exponential backoff for transient failures
    - Proper error classification (auth, not found, rate limit, etc.)
    - Request headers for authentication and tenant isolation

    Usage:
        # API key loaded from ADEN_API_KEY environment variable
        config = AdenClientConfig(
            base_url="https://api.adenhq.com",
        )

        client = AdenCredentialClient(config)

        # Fetch a credential
        cred = client.get_credential("hubspot")
        if cred:
            headers = {"Authorization": f"Bearer {cred.access_token}"}

        # List all integrations
        integrations = client.list_integrations()
        for info in integrations:
            print(f"{info.integration_id}: {info.status}")

        # Clean up
        client.close()
    """

    def __init__(self, config: AdenClientConfig):
        """
        Initialize the Aden client.

        Args:
            config: Client configuration including base URL and API key.
        """
        self.config = config
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
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

                # Handle specific error codes
                if response.status_code == 401:
                    raise AdenAuthenticationError("Agent API key is invalid or revoked")

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
                    if data.get("error") == "refresh_failed":
                        raise AdenRefreshError(
                            data.get("message", "Token refresh failed"),
                            requires_reauthorization=data.get("requires_reauthorization", False),
                            reauthorization_url=data.get("reauthorization_url"),
                        )

                # Success or other error
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
                # Don't retry these errors
                raise

        # Should not reach here, but just in case
        raise AdenClientError(
            f"Request failed after {self.config.retry_attempts} attempts"
        ) from last_error

    def get_credential(self, integration_id: str) -> AdenCredentialResponse | None:
        """
        Fetch the current credential for an integration.

        The Aden server may refresh the token internally if it's expired
        before returning it.

        Args:
            integration_id: The integration identifier (e.g., 'hubspot').

        Returns:
            Credential response with access token, or None if not found.

        Raises:
            AdenAuthenticationError: If API key is invalid.
            AdenClientError: For connection failures.
        """
        try:
            response = self._request_with_retry("GET", f"/v1/credentials/{integration_id}")
            data = response.json()
            return AdenCredentialResponse.from_dict(data, integration_id=integration_id)
        except AdenNotFoundError:
            return None

    def request_refresh(self, integration_id: str) -> AdenCredentialResponse:
        """
        Request the Aden server to refresh the token.

        Use this when the local store detects an expired or near-expiry token.
        The Aden server handles the actual OAuth2 refresh token flow.

        Args:
            integration_id: The integration identifier.

        Returns:
            Credential response with new access token.

        Raises:
            AdenRefreshError: If refresh fails (may require re-authorization).
            AdenNotFoundError: If integration not found.
            AdenAuthenticationError: If API key is invalid.
            AdenRateLimitError: If rate limited.
        """
        response = self._request_with_retry("POST", f"/v1/credentials/{integration_id}/refresh")
        data = response.json()
        return AdenCredentialResponse.from_dict(data, integration_id=integration_id)

    def list_integrations(self) -> list[AdenIntegrationInfo]:
        """
        List all integrations available for this agent/tenant.

        Returns:
            List of integration info objects.

        Raises:
            AdenAuthenticationError: If API key is invalid.
            AdenClientError: For connection failures.
        """
        response = self._request_with_retry("GET", "/v1/credentials")
        data = response.json()
        return [AdenIntegrationInfo.from_dict(item) for item in data.get("integrations", [])]

    def validate_token(self, integration_id: str) -> dict[str, Any]:
        """
        Check if a token is still valid without fetching it.

        Args:
            integration_id: The integration identifier.

        Returns:
            Dict with 'valid' bool and optional 'expires_at', 'reason',
            'requires_reauthorization', 'reauthorization_url'.

        Raises:
            AdenNotFoundError: If integration not found.
            AdenAuthenticationError: If API key is invalid.
        """
        response = self._request_with_retry("GET", f"/v1/credentials/{integration_id}/validate")
        return response.json()

    def report_usage(
        self,
        integration_id: str,
        operation: str,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Report credential usage statistics to Aden.

        This is optional and used for analytics/billing.

        Args:
            integration_id: The integration identifier.
            operation: Operation name (e.g., 'api_call').
            status: Operation status ('success', 'error').
            metadata: Additional operation metadata.
        """
        try:
            self._request_with_retry(
                "POST",
                f"/v1/credentials/{integration_id}/usage",
                json={
                    "operation": operation,
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "metadata": metadata or {},
                },
            )
        except Exception as e:
            # Usage reporting is best-effort, don't fail on errors
            logger.warning(f"Failed to report usage for '{integration_id}': {e}")

    def health_check(self) -> dict[str, Any]:
        """
        Check Aden server health and connectivity.

        Returns:
            Dict with 'status', 'version', 'timestamp', and optionally 'error'.
        """
        try:
            client = self._get_client()
            response = client.get("/health")
            if response.status_code == 200:
                data = response.json()
                data["latency_ms"] = response.elapsed.total_seconds() * 1000
                return data
            return {
                "status": "degraded",
                "error": f"Unexpected status code: {response.status_code}",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> AdenCredentialClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()
