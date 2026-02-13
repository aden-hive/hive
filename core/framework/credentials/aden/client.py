"""
Aden Credential Client.

HTTP client for communicating with the Aden authentication server.
The Aden server handles OAuth2 authorization flows and token management.
This client fetches tokens and delegates refresh operations to Aden.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    api_key: str | None = None
    tenant_id: str | None = None
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 1.0

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("ADEN_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "Aden API key not provided. Set ADEN_API_KEY or pass api_key."
                )


@dataclass
class AdenCredentialResponse:
    """Response from Aden server containing credential data."""

    integration_id: str
    integration_type: str
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], integration_id: str | None = None
    ) -> "AdenCredentialResponse":

        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(
                data["expires_at"].replace("Z", "+00:00")
            )

        resolved_id = (
            integration_id
            or data.get("integration_id")
            or data.get("alias")
            or data.get("provider", "")
        )

        resolved_type = data.get("integration_type") or data.get("provider", "")

        metadata = data.get("metadata")
        if metadata is None and data.get("email"):
            metadata = {"email": data.get("email")}
        if metadata is None:
            metadata = {}

        return cls(
            integration_id=resolved_id,
            integration_type=resolved_type,
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
    status: str
    expires_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdenIntegrationInfo":

        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(
                data["expires_at"].replace("Z", "+00:00")
            )

        return cls(
            integration_id=data["integration_id"],
            integration_type=data.get("provider", data["integration_id"]),
            status=data.get("status", "unknown"),
            expires_at=expires_at,
        )


class AdenCredentialClient:
    """HTTP client for Aden credential server."""

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

        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.config.retry_attempts):

            try:
                response = client.request(method, path, **kwargs)

                if response.status_code == 401:
                    raise AdenAuthenticationError("Invalid API key")

                if response.status_code == 404:
                    raise AdenNotFoundError(f"Integration not found: {path}")

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise AdenRateLimitError(
                        "Rate limited",
                        retry_after=retry_after,
                    )

                if response.status_code == 400:
                    data = response.json()
                    if data.get("error") == "refresh_failed":
                        raise AdenRefreshError(
                            data.get("message", "Refresh failed"),
                            requires_reauthorization=data.get(
                                "requires_reauthorization", False
                            ),
                            reauthorization_url=data.get("reauthorization_url"),
                        )

                response.raise_for_status()
                return response

            except (httpx.ConnectError, httpx.TimeoutException) as e:

                last_error = e

                if attempt < self.config.retry_attempts - 1:
                    delay = self.config.retry_delay * (2**attempt)

                    logger.warning(
                        f"Request failed (attempt {attempt + 1}), retrying in {delay}s: {e}"
                    )

                    time.sleep(delay)

                else:
                    raise AdenClientError(
                        f"Failed to connect: {e}"
                    ) from e

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

    def get_credential(self, integration_id: str) -> AdenCredentialResponse | None:

        try:
            response = self._request_with_retry(
                "GET",
                f"/v1/credentials/{integration_id}",
            )

            data = response.json()

            return AdenCredentialResponse.from_dict(
                data,
                integration_id=integration_id,
            )

        except AdenNotFoundError:
            return None

    def request_refresh(self, integration_id: str) -> AdenCredentialResponse:

        response = self._request_with_retry(
            "POST",
            f"/v1/credentials/{integration_id}/refresh",
        )

        data = response.json()

        return AdenCredentialResponse.from_dict(
            data,
            integration_id=integration_id,
        )

    def list_integrations(self) -> list[AdenIntegrationInfo]:

        response = self._request_with_retry("GET", "/v1/credentials")

        data = response.json()

        return [
            AdenIntegrationInfo.from_dict(item)
            for item in data.get("integrations", [])
        ]

    def validate_token(self, integration_id: str) -> dict[str, Any]:

        response = self._request_with_retry(
            "GET",
            f"/v1/credentials/{integration_id}/validate",
        )

        return response.json()

    def report_usage(
        self,
        integration_id: str,
        operation: str,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:

        try:
            self._request_with_retry(
                "POST",
                f"/v1/credentials/{integration_id}/usage",
                json={
                    "operation": operation,
                    "status": status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": metadata or {},
                },
            )

        except Exception as e:
            logger.warning(
                f"Failed to report usage for '{integration_id}': {e}"
            )

    def health_check(self) -> dict[str, Any]:

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

        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "AdenCredentialClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
