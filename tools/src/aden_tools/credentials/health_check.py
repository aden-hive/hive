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


class GoogleHealthChecker:
    """Health checker for Google OAuth tokens (Gmail, Calendar, Sheets)."""

    ENDPOINTS: dict[str, str] = {
        "gmail": "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        "calendar": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        "sheets": "https://sheets.googleapis.com/v4/spreadsheets/healthcheck_nonexistent",
    }
    TIMEOUT = 10.0

    def check(self, access_token: str) -> HealthCheckResult:
        """
        Validate Google OAuth token against Gmail, Calendar, and Sheets APIs.

        Hits a lightweight endpoint for each service. A 401 on any endpoint
        means the token is invalid (fail fast). A 403 means the token lacks
        that service's scope. For Sheets, a 404 counts as success (scope is
        valid, the spreadsheet just doesn't exist).
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        missing_scopes: list[str] = []

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                for scope, url in self.ENDPOINTS.items():
                    params = {"maxResults": "1"} if scope == "calendar" else {}
                    response = client.get(url, headers=headers, params=params)

                    if response.status_code == 401:
                        return HealthCheckResult(
                            valid=False,
                            message="Google token is invalid or expired",
                            details={"status_code": 401},
                        )
                    if response.status_code == 403:
                        missing_scopes.append(scope)
                        continue
                    # Sheets returns 404 for a non-existent spreadsheet — that's fine,
                    # it means the token + scope are valid.
                    if response.status_code in (200, 404):
                        continue
                    # Unexpected status — not a scope issue, but not healthy either
                    return HealthCheckResult(
                        valid=False,
                        message=f"Google {scope} API returned status {response.status_code}",
                        details={"status_code": response.status_code, "scope": scope},
                    )

            if missing_scopes:
                return HealthCheckResult(
                    valid=False,
                    message=f"Google token lacks scopes for: {', '.join(missing_scopes)}",
                    details={"status_code": 403, "missing_scopes": missing_scopes},
                )

            return HealthCheckResult(
                valid=True,
                message="Google credentials valid (Gmail, Calendar, Sheets)",
            )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Google API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            error_msg = str(e)
            if "Bearer" in error_msg or "Authorization" in error_msg:
                error_msg = "Request failed (details redacted for security)"
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Google: {error_msg}",
                details={"error": error_msg},
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


class SlackHealthChecker:
    """Health checker for Slack bot tokens."""

    ENDPOINT = "https://slack.com/api/auth.test"
    TIMEOUT = 10.0

    def check(self, bot_token: str) -> HealthCheckResult:
        """
        Validate Slack bot token by calling auth.test.

        Makes a POST request to auth.test to verify the token works.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.post(
                    self.ENDPOINT,
                    headers={"Authorization": f"Bearer {bot_token}"},
                )

                if response.status_code != 200:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Slack API returned HTTP {response.status_code}",
                        details={"status_code": response.status_code},
                    )

                data = response.json()
                if data.get("ok"):
                    return HealthCheckResult(
                        valid=True,
                        message="Slack bot token valid",
                        details={
                            "team": data.get("team"),
                            "user": data.get("user"),
                            "bot_id": data.get("bot_id"),
                        },
                    )
                else:
                    error = data.get("error", "unknown_error")
                    return HealthCheckResult(
                        valid=False,
                        message=f"Slack token invalid: {error}",
                        details={"error": error},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Slack API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Slack: {e}",
                details={"error": str(e)},
            )


class AnthropicHealthChecker:
    """Health checker for Anthropic API credentials."""

    ENDPOINT = "https://api.anthropic.com/v1/messages"
    TIMEOUT = 10.0

    def check(self, api_key: str) -> HealthCheckResult:
        """
        Validate Anthropic API key without consuming tokens.

        Sends a deliberately invalid request (empty messages) to the messages endpoint.
        A 401 means invalid key; 400 (bad request) means the key authenticated
        but the payload was rejected — confirming the key is valid without
        generating any tokens. 429 (rate limited) also indicates a valid key.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.post(
                    self.ENDPOINT,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    # Empty messages triggers 400 (not 200), so no tokens are consumed.
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1,
                        "messages": [],
                    },
                )

                if response.status_code == 200:
                    return HealthCheckResult(
                        valid=True,
                        message="Anthropic API key valid",
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="Anthropic API key is invalid",
                        details={"status_code": 401},
                    )
                elif response.status_code == 429:
                    # Rate limited but key is valid
                    return HealthCheckResult(
                        valid=True,
                        message="Anthropic API key valid (rate limited)",
                        details={"status_code": 429, "rate_limited": True},
                    )
                elif response.status_code == 400:
                    # Bad request but key authenticated - key is valid
                    return HealthCheckResult(
                        valid=True,
                        message="Anthropic API key valid",
                        details={"status_code": 400},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Anthropic API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Anthropic API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Anthropic API: {e}",
                details={"error": str(e)},
            )


class GitHubHealthChecker:
    """Health checker for GitHub Personal Access Token."""

    ENDPOINT = "https://api.github.com/user"
    TIMEOUT = 10.0

    def check(self, access_token: str) -> HealthCheckResult:
        """
        Validate GitHub token by fetching the authenticated user.

        Returns the authenticated username on success.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    username = data.get("login", "unknown")
                    return HealthCheckResult(
                        valid=True,
                        message=f"GitHub token valid (authenticated as {username})",
                        details={"username": username},
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="GitHub token is invalid or expired",
                        details={"status_code": 401},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message="GitHub token lacks required permissions",
                        details={"status_code": 403},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"GitHub API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="GitHub API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to GitHub API: {e}",
                details={"error": str(e)},
            )


class DiscordHealthChecker:
    """Health checker for Discord bot tokens."""

    ENDPOINT = "https://discord.com/api/v10/users/@me"
    TIMEOUT = 10.0

    def check(self, bot_token: str) -> HealthCheckResult:
        """
        Validate Discord bot token by fetching the bot's user info.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    headers={"Authorization": f"Bot {bot_token}"},
                )

                if response.status_code == 200:
                    data = response.json()
                    username = data.get("username", "unknown")
                    return HealthCheckResult(
                        valid=True,
                        message=f"Discord bot token valid (bot: {username})",
                        details={"username": username, "id": data.get("id")},
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="Discord bot token is invalid",
                        details={"status_code": 401},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message="Discord bot token lacks required permissions",
                        details={"status_code": 403},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Discord API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Discord API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Discord API: {e}",
                details={"error": str(e)},
            )


class ResendHealthChecker:
    """Health checker for Resend API credentials."""

    ENDPOINT = "https://api.resend.com/domains"
    TIMEOUT = 10.0

    def check(self, api_key: str) -> HealthCheckResult:
        """
        Validate Resend API key by listing domains.

        A successful response confirms the key is valid.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                )

                if response.status_code == 200:
                    return HealthCheckResult(
                        valid=True,
                        message="Resend API key valid",
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message="Resend API key is invalid",
                        details={"status_code": 401},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message="Resend API key lacks required permissions",
                        details={"status_code": 403},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Resend API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Resend API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Resend API: {e}",
                details={"error": str(e)},
            )


class GoogleMapsHealthChecker:
    """Health checker for Google Maps Platform API key."""

    ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
    TIMEOUT = 10.0

    def check(self, api_key: str) -> HealthCheckResult:
        """
        Validate Google Maps API key with a lightweight geocode request.

        Makes a minimal geocode request for a well-known address to verify
        the key is valid and the Geocoding API is enabled.
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.ENDPOINT,
                    params={
                        "address": "1600 Amphitheatre Parkway",
                        "key": api_key,
                    },
                )

                if response.status_code != 200:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Google Maps API returned HTTP {response.status_code}",
                        details={"status_code": response.status_code},
                    )

                data = response.json()
                status = data.get("status", "UNKNOWN_ERROR")

                if status == "OK":
                    return HealthCheckResult(
                        valid=True,
                        message="Google Maps API key valid",
                    )
                elif status == "REQUEST_DENIED":
                    return HealthCheckResult(
                        valid=False,
                        message="Google Maps API key is invalid or Geocoding API not enabled",
                        details={"status": status},
                    )
                elif status in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
                    # Quota exceeded but key itself is valid
                    return HealthCheckResult(
                        valid=True,
                        message="Google Maps API key valid (quota exceeded)",
                        details={"status": status, "rate_limited": True},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"Google Maps API returned status: {status}",
                        details={"status": status},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message="Google Maps API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to Google Maps API: {e}",
                details={"error": str(e)},
            )


# Registry of health checkers
HEALTH_CHECKERS: dict[str, CredentialHealthChecker] = {
    "discord": DiscordHealthChecker(),
    "hubspot": HubSpotHealthChecker(),
    "brave_search": BraveSearchHealthChecker(),
    "google": GoogleHealthChecker(),
    "slack": SlackHealthChecker(),
    "google_search": GoogleSearchHealthChecker(),
    "google_maps": GoogleMapsHealthChecker(),
    "anthropic": AnthropicHealthChecker(),
    "github": GitHubHealthChecker(),
    "resend": ResendHealthChecker(),
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
