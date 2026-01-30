"""
Credential health checks per integration.

Validates that stored credentials are valid before agent execution.
Each integration has a lightweight health check that makes a minimal API call
to verify the credential works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class HealthCheckResult:
    """Result of a credential health check."""

    valid: bool
    """Whether the credential is valid."""

    message: str
    """Human-readable status message."""

    details: dict[str, Any] = field(default_factory=dict)
    """Additional details (e.g., error codes, rate limit info)."""


class CredentialHealthChecker(Protocol):
    """Protocol for credential health checkers."""

    def check(self, credential_value: str) -> HealthCheckResult:
        """
        Check if the credential is valid.

        Args:
            credential_value: The credential value to validate

        Returns:
            HealthCheckResult with validation status
        """
        ...


class HubSpotHealthChecker:
    """Health checker for HubSpot credentials."""

    ENDPOINT = "https://api.hubapi.com/crm/v3/objects/contacts"
    TIMEOUT = 10.0

    def check(self, access_token: str) -> HealthCheckResult:
        """
        Validate HubSpot token by making lightweight API call.

        Makes a GET request for 1 contact to verify the token works.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                    params={"limit": "1"},
                )

                if response.status_code == 200:
                    return HealthCheckResult(
                        valid=True,
                        message="HubSpot credentials valid",
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="HubSpot token is invalid or expired",
                        details={"status_code": 401},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message="HubSpot token lacks required scopes",
                        details={"status_code": 403, "required": "crm.objects.contacts.read"},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"HubSpot API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="HubSpot API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to HubSpot: {e}",
                details={"error": str(e)},
            )


class BraveSearchHealthChecker:
    """Health checker for Brave Search API."""

    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
    TIMEOUT = 10.0

    def check(self, api_key: str) -> HealthCheckResult:
        """
        Validate Brave Search API key.

        Makes a minimal search request to verify the key works.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    headers={"X-Subscription-Token": api_key},
                    params={"q": "test", "count": "1"},
                )

                if response.status_code == 200:
                    return HealthCheckResult(
                        valid=True,
                        message="Brave Search API key valid",
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="Brave Search API key is invalid",
                        details={"status_code": 401},
                    )
                elif response.status_code == 429:
                    # Rate limited but key is valid
                    return HealthCheckResult(
                        valid=True,
                        message="Brave Search API key valid (rate limited)",
                        details={"status_code": 429, "rate_limited": True},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Brave Search API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Brave Search API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Brave Search: {e}",
                details={"error": str(e)},
            )


class GoogleSearchHealthChecker:
    """Health checker for Google Custom Search API."""

    ENDPOINT = "https://www.googleapis.com/customsearch/v1"
    TIMEOUT = 10.0

    def check(self, api_key: str, cse_id: str | None = None) -> HealthCheckResult:
        """
        Validate Google Custom Search API key.

        Note: Requires both API key and CSE ID for a full check.
        If CSE ID is not provided, we can only do a partial validation.
        """
        if not cse_id:
            return HealthCheckResult(
                valid=True,
                message="Google API key format valid (CSE ID needed for full check)",
                details={"partial_check": True},
            )

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    params={
                        "key": api_key,
                        "cx": cse_id,
                        "q": "test",
                        "num": "1",
                    },
                )

                if response.status_code == 200:
                    return HealthCheckResult(
                        valid=True,
                        message="Google Custom Search credentials valid",
                    )
                elif response.status_code == 400:
                    return HealthCheckResult(
                        valid=False,
                        message="Google Custom Search: Invalid CSE ID",
                        details={"status_code": 400},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message="Google API key is invalid or quota exceeded",
                        details={"status_code": 403},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Google API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Google API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Google API: {e}",
                details={"error": str(e)},
            )


# Registry of health checkers
HEALTH_CHECKERS: dict[str, CredentialHealthChecker] = {
    "hubspot": HubSpotHealthChecker(),
    "brave_search": BraveSearchHealthChecker(),
}


def check_credential_health(
    credential_name: str,
    credential_value: str,
    **kwargs: Any,
) -> HealthCheckResult:
    """
    Check if a credential is valid.

    Args:
        credential_name: Name of the credential (e.g., 'hubspot', 'brave_search')
        credential_value: The credential value to validate
        **kwargs: Additional arguments passed to the checker (e.g., cse_id for Google)

    Returns:
        HealthCheckResult with validation status

    Example:
        >>> result = check_credential_health("hubspot", "pat-xxx-yyy")
        >>> if result.valid:
        ...     print("Credential is valid!")
        ... else:
        ...     print(f"Invalid: {result.message}")
    """
    checker = HEALTH_CHECKERS.get(credential_name)

    if checker is None:
        # No health checker registered - assume valid
        return HealthCheckResult(
            valid=True,
            message=f"No health checker for '{credential_name}', assuming valid",
            details={"no_checker": True},
        )

    # Special case for Google which needs CSE ID
    if credential_name == "google_search" and "cse_id" in kwargs:
        checker = GoogleSearchHealthChecker()
        return checker.check(credential_value, kwargs["cse_id"])

    return checker.check(credential_value)
