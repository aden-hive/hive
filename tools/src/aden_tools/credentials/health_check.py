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


class OAuthBearerHealthChecker:
    """Generic health checker for OAuth2 Bearer token credentials.

    Validates by making a GET request with ``Authorization: Bearer <token>``
    to the given endpoint.  Reused for Google Gmail, Google Calendar, and as
    the automatic fallback for any credential spec that defines a
    ``health_check_endpoint`` but has no dedicated checker.
    """

    TIMEOUT = 10.0

    def __init__(self, endpoint: str, service_name: str = "Service"):
        self.endpoint = endpoint
        self.service_name = service_name

    def _extract_identity(self, data: dict) -> dict[str, str]:
        """Override to extract identity fields from a successful response."""
        return {}

    def check(self, access_token: str) -> HealthCheckResult:
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )

                if response.status_code == 200:
                    identity: dict[str, str] = {}
                    try:
                        data = response.json()
                        identity = self._extract_identity(data)
                    except Exception:
                        pass  # Identity extraction is best-effort
                    return HealthCheckResult(
                        valid=True,
                        message=f"{self.service_name} credentials valid",
                        details={"identity": identity} if identity else {},
                    )
                elif response.status_code == 401:
                    return HealthCheckResult(
                        valid=False,
                        message=f"{self.service_name} token is invalid or expired",
                        details={"status_code": 401},
                    )
                elif response.status_code == 403:
                    return HealthCheckResult(
                        valid=False,
                        message=f"{self.service_name} token lacks required scopes",
                        details={"status_code": 403},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message=f"{self.service_name} API returned status {response.status_code}",
                        details={"status_code": response.status_code},
                    )
        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message=f"{self.service_name} API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            error_msg = str(e)
            if "Bearer" in error_msg or "Authorization" in error_msg:
                error_msg = "Request failed (details redacted for security)"
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to {self.service_name}: {error_msg}",
                details={"error": error_msg},
            )


class BaseHttpHealthChecker:
    """Configurable base class for HTTP-based credential health checkers.

    Reduces boilerplate by handling the common HTTP request/response/error pattern.
    Subclasses configure via class constants and override hooks as needed.

    Supports five auth patterns:
    - AUTH_BEARER: Authorization: Bearer <token>
    - AUTH_HEADER: Custom header name/value template
    - AUTH_QUERY: Token as query parameter
    - AUTH_BASIC: HTTP Basic Authentication
    - AUTH_URL: Token embedded in URL (e.g., Telegram)

    Example::

        class CalcomHealthChecker(BaseHttpHealthChecker):
            ENDPOINT = "https://api.cal.com/v1/me"
            SERVICE_NAME = "Cal.com"
            AUTH_TYPE = "query"
            AUTH_QUERY_PARAM_NAME = "apiKey"
    """

    # Auth pattern constants
    AUTH_BEARER = "bearer"
    AUTH_HEADER = "header"
    AUTH_QUERY = "query"
    AUTH_BASIC = "basic"
    AUTH_URL = "url"

    # Subclass configuration
    ENDPOINT: str = ""
    SERVICE_NAME: str = ""
    HTTP_METHOD: str = "GET"
    TIMEOUT: float = 10.0

    # Auth configuration
    AUTH_TYPE: str = AUTH_BEARER
    AUTH_HEADER_NAME: str = "Authorization"
    AUTH_HEADER_TEMPLATE: str = "Bearer {token}"
    AUTH_QUERY_PARAM_NAME: str = "key"

    # Status code interpretation
    VALID_STATUSES: frozenset[int] = frozenset({200})
    RATE_LIMITED_STATUSES: frozenset[int] = frozenset({429})
    AUTHENTICATED_ERROR_STATUSES: frozenset[int] = frozenset()
    INVALID_STATUSES: frozenset[int] = frozenset({401})
    FORBIDDEN_STATUSES: frozenset[int] = frozenset({403})

    def _build_url(self, credential_value: str) -> str:
        """Build request URL. Override for URL-template auth."""
        return self.ENDPOINT

    def _build_headers(self, credential_value: str) -> dict[str, str]:
        """Build request headers based on AUTH_TYPE."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.AUTH_TYPE == self.AUTH_BEARER:
            headers["Authorization"] = f"Bearer {credential_value}"
        elif self.AUTH_TYPE == self.AUTH_HEADER:
            headers[self.AUTH_HEADER_NAME] = self.AUTH_HEADER_TEMPLATE.format(
                token=credential_value
            )
        return headers

    def _build_params(self, credential_value: str) -> dict[str, str]:
        """Build query parameters. Includes auth param for AUTH_QUERY type."""
        if self.AUTH_TYPE == self.AUTH_QUERY:
            return {self.AUTH_QUERY_PARAM_NAME: credential_value}
        return {}

    def _build_auth(self, credential_value: str) -> tuple[str, str] | None:
        """Build HTTP Basic auth tuple for AUTH_BASIC type."""
        if self.AUTH_TYPE == self.AUTH_BASIC:
            return (credential_value, "")
        return None

    def _build_json_body(self, credential_value: str) -> dict | None:
        """Build JSON request body. Override for POST requests that need one."""
        return None

    def _extract_identity(self, data: dict) -> dict[str, str]:
        """Extract identity info from successful response. Override in subclass."""
        return {}

    def _interpret_response(self, response: httpx.Response) -> HealthCheckResult:
        """Interpret HTTP response. Override for non-standard status logic."""
        status = response.status_code

        if status in self.VALID_STATUSES:
            identity: dict[str, str] = {}
            try:
                data = response.json()
                identity = self._extract_identity(data)
            except Exception:
                pass
            return HealthCheckResult(
                valid=True,
                message=f"{self.SERVICE_NAME} credentials valid",
                details={"identity": identity} if identity else {},
            )
        elif status in self.RATE_LIMITED_STATUSES:
            return HealthCheckResult(
                valid=True,
                message=f"{self.SERVICE_NAME} credentials valid (rate limited)",
                details={"status_code": status, "rate_limited": True},
            )
        elif status in self.AUTHENTICATED_ERROR_STATUSES:
            return HealthCheckResult(
                valid=True,
                message=f"{self.SERVICE_NAME} credentials valid",
                details={"status_code": status},
            )
        elif status in self.INVALID_STATUSES:
            return HealthCheckResult(
                valid=False,
                message=f"{self.SERVICE_NAME} credentials are invalid or expired",
                details={"status_code": status},
            )
        elif status in self.FORBIDDEN_STATUSES:
            return HealthCheckResult(
                valid=False,
                message=f"{self.SERVICE_NAME} credentials lack required permissions",
                details={"status_code": status},
            )
        else:
            return HealthCheckResult(
                valid=False,
                message=f"{self.SERVICE_NAME} API returned status {status}",
                details={"status_code": status},
            )

    def check(self, credential_value: str) -> HealthCheckResult:
        """Execute the health check. Normally not overridden."""
        try:
            url = self._build_url(credential_value)
            headers = self._build_headers(credential_value)
            params = self._build_params(credential_value)
            auth = self._build_auth(credential_value)
            json_body = self._build_json_body(credential_value)

            with httpx.Client(timeout=self.TIMEOUT) as client:
                kwargs: dict[str, Any] = {"headers": headers}
                if params:
                    kwargs["params"] = params
                if auth:
                    kwargs["auth"] = auth
                if json_body is not None:
                    kwargs["json"] = json_body

                if self.HTTP_METHOD.upper() == "POST":
                    response = client.post(url, **kwargs)
                else:
                    response = client.get(url, **kwargs)

            return self._interpret_response(response)

        except httpx.TimeoutException:
            return HealthCheckResult(
                valid=False,
                message=f"{self.SERVICE_NAME} API request timed out",
                details={"error": "timeout"},
            )
        except httpx.RequestError as e:
            error_msg = str(e)
            if any(s in error_msg for s in ("Bearer", "Authorization", "api_key", "token")):
                error_msg = "Request failed (details redacted for security)"
            return HealthCheckResult(
                valid=False,
                message=f"Failed to connect to {self.SERVICE_NAME}: {error_msg}",
                details={"error": error_msg},
            )


class GoogleCalendarHealthChecker(OAuthBearerHealthChecker):
    """Health checker for Google Calendar OAuth tokens."""

    def __init__(self):
        super().__init__(
            endpoint="https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1",
            service_name="Google Calendar",
        )

    def _extract_identity(self, data: dict) -> dict[str, str]:
        # Primary calendar ID is the user's email
        for item in data.get("items", []):
            if item.get("primary"):
                cal_id = item.get("id", "")
                if "@" in cal_id:
                    return {"email": cal_id}
        return {}


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
                    identity: dict[str, str] = {}
                    if data.get("team"):
                        identity["workspace"] = data["team"]
                    if data.get("user"):
                        identity["username"] = data["user"]
                    return HealthCheckResult(
                        valid=True,
                        message="Slack bot token valid",
                        details={
                            "team": data.get("team"),
                            "user": data.get("user"),
                            "bot_id": data.get("bot_id"),
                            "identity": identity,
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
                    identity: dict[str, str] = {}
                    if username and username != "unknown":
                        identity["username"] = username
                    return HealthCheckResult(
                        valid=True,
                        message=f"GitHub token valid (authenticated as {username})",
                        details={"username": username, "identity": identity},
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
                    identity: dict[str, str] = {}
                    if username and username != "unknown":
                        identity["username"] = username
                    if data.get("id"):
                        identity["account_id"] = data["id"]
                    return HealthCheckResult(
                        valid=True,
                        message=f"Discord bot token valid (bot: {username})",
                        details={"username": username, "id": data.get("id"), "identity": identity},
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


class GoogleGmailHealthChecker(OAuthBearerHealthChecker):
    """Health checker for Google Gmail OAuth tokens."""

    def __init__(self):
        super().__init__(
            endpoint="https://gmail.googleapis.com/gmail/v1/users/me/profile",
            service_name="Gmail",
        )

    def _extract_identity(self, data: dict) -> dict[str, str]:
        email = data.get("emailAddress")
        return {"email": email} if email else {}


# --- New checkers using BaseHttpHealthChecker ---


class StripeHealthChecker(BaseHttpHealthChecker):
    """Health checker for Stripe API key."""

    ENDPOINT = "https://api.stripe.com/v1/balance"
    SERVICE_NAME = "Stripe"


class ExaSearchHealthChecker(BaseHttpHealthChecker):
    """Health checker for Exa Search API key."""

    ENDPOINT = "https://api.exa.ai/search"
    SERVICE_NAME = "Exa Search"
    HTTP_METHOD = "POST"

    def _build_json_body(self, credential_value: str) -> dict:
        return {"query": "test", "numResults": 1}


class GoogleDocsHealthChecker(OAuthBearerHealthChecker):
    """Health checker for Google Docs OAuth tokens."""

    def __init__(self):
        super().__init__(
            endpoint="https://docs.googleapis.com/v1/documents/1",
            service_name="Google Docs",
        )


class CalcomHealthChecker(BaseHttpHealthChecker):
    """Health checker for Cal.com API key."""

    ENDPOINT = "https://api.cal.com/v1/me"
    SERVICE_NAME = "Cal.com"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_QUERY
    AUTH_QUERY_PARAM_NAME = "apiKey"


class SerpApiHealthChecker(BaseHttpHealthChecker):
    """Health checker for SerpAPI key."""

    ENDPOINT = "https://serpapi.com/account.json"
    SERVICE_NAME = "SerpAPI"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_QUERY
    AUTH_QUERY_PARAM_NAME = "api_key"


class ApolloHealthChecker(BaseHttpHealthChecker):
    """Health checker for Apollo.io API key."""

    ENDPOINT = "https://api.apollo.io/v1/auth/health"
    SERVICE_NAME = "Apollo"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_QUERY
    AUTH_QUERY_PARAM_NAME = "api_key"


class TelegramHealthChecker(BaseHttpHealthChecker):
    """Health checker for Telegram bot token."""

    SERVICE_NAME = "Telegram"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_URL

    def _build_url(self, credential_value: str) -> str:
        return f"https://api.telegram.org/bot{credential_value}/getMe"

    def _build_headers(self, credential_value: str) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _interpret_response(self, response: httpx.Response) -> HealthCheckResult:
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("ok"):
                    username = data.get("result", {}).get("username", "unknown")
                    identity = {"username": username} if username != "unknown" else {}
                    return HealthCheckResult(
                        valid=True,
                        message=f"Telegram bot token valid (bot: @{username})",
                        details={"identity": identity},
                    )
                else:
                    return HealthCheckResult(
                        valid=False,
                        message="Telegram bot token is invalid",
                        details={"telegram_error": data.get("description", "")},
                    )
            except Exception:
                return HealthCheckResult(
                    valid=True,
                    message="Telegram credentials valid",
                )
        elif response.status_code == 401:
            return HealthCheckResult(
                valid=False,
                message="Telegram bot token is invalid",
                details={"status_code": 401},
            )
        else:
            return HealthCheckResult(
                valid=False,
                message=f"Telegram API returned status {response.status_code}",
                details={"status_code": response.status_code},
            )


class NewsdataHealthChecker(BaseHttpHealthChecker):
    """Health checker for Newsdata.io API key."""

    ENDPOINT = "https://newsdata.io/api/1/news"
    SERVICE_NAME = "Newsdata"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_QUERY
    AUTH_QUERY_PARAM_NAME = "apikey"

    def _build_params(self, credential_value: str) -> dict[str, str]:
        params = super()._build_params(credential_value)
        params["q"] = "test"
        return params


class FinlightHealthChecker(BaseHttpHealthChecker):
    """Health checker for Finlight API key."""

    ENDPOINT = "https://api.finlight.me/v1/news"
    SERVICE_NAME = "Finlight"


class BrevoHealthChecker(BaseHttpHealthChecker):
    """Health checker for Brevo API key."""

    ENDPOINT = "https://api.brevo.com/v3/account"
    SERVICE_NAME = "Brevo"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_HEADER
    AUTH_HEADER_NAME = "api-key"
    AUTH_HEADER_TEMPLATE = "{token}"

    def _extract_identity(self, data: dict) -> dict[str, str]:
        identity: dict[str, str] = {}
        if data.get("email"):
            identity["email"] = data["email"]
        if data.get("companyName"):
            identity["company"] = data["companyName"]
        return identity


# Registry of health checkers
HEALTH_CHECKERS: dict[str, CredentialHealthChecker] = {
    "discord": DiscordHealthChecker(),
    "hubspot": HubSpotHealthChecker(),
    "brave_search": BraveSearchHealthChecker(),
    "google_calendar_oauth": GoogleCalendarHealthChecker(),
    "google": GoogleGmailHealthChecker(),
    "slack": SlackHealthChecker(),
    "google_search": GoogleSearchHealthChecker(),
    "google_maps": GoogleMapsHealthChecker(),
    "anthropic": AnthropicHealthChecker(),
    "github": GitHubHealthChecker(),
    "resend": ResendHealthChecker(),
    "stripe": StripeHealthChecker(),
    "exa_search": ExaSearchHealthChecker(),
    "google_docs": GoogleDocsHealthChecker(),
    "calcom": CalcomHealthChecker(),
    "serpapi": SerpApiHealthChecker(),
    "apollo": ApolloHealthChecker(),
    "telegram": TelegramHealthChecker(),
    "newsdata": NewsdataHealthChecker(),
    "finlight": FinlightHealthChecker(),
    "brevo": BrevoHealthChecker(),
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
        **kwargs: Additional arguments passed to the checker.
            - cse_id: CSE ID for Google Custom Search
            - health_check_endpoint: Fallback endpoint URL when no dedicated
              checker is registered. Used automatically by
              ``validate_agent_credentials`` from the credential spec.
            - health_check_method: HTTP method for fallback (default GET).

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
        # No dedicated checker — try generic fallback using the spec's endpoint
        endpoint = kwargs.get("health_check_endpoint")
        if endpoint:
            checker = OAuthBearerHealthChecker(
                endpoint=endpoint,
                service_name=credential_name.replace("_", " ").title(),
            )
        else:
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


def validate_integration_wiring(credential_name: str) -> list[str]:
    """Check that a credential integration is fully wired up.

    Returns a list of issues found. Empty list means everything is correct.

    Use during development to verify a new integration has all required pieces:
    CredentialSpec, health checker, endpoint consistency, and required fields.

    Args:
        credential_name: The credential name to validate (e.g., 'jira').

    Returns:
        List of issue descriptions. Empty if fully wired.

    Example::

        issues = validate_integration_wiring("stripe")
        for issue in issues:
            print(f"  - {issue}")
    """
    from . import CREDENTIAL_SPECS

    issues: list[str] = []

    # 1. Check spec exists
    spec = CREDENTIAL_SPECS.get(credential_name)
    if spec is None:
        issues.append(
            f"No CredentialSpec for '{credential_name}' in CREDENTIAL_SPECS. "
            f"Add it to the appropriate category file and import in __init__.py."
        )
        return issues

    # 2. Check required fields
    if not spec.env_var:
        issues.append("CredentialSpec.env_var is empty")
    if not spec.description:
        issues.append("CredentialSpec.description is empty")
    if not spec.tools and not spec.node_types:
        issues.append("CredentialSpec has no tools or node_types")
    if not spec.help_url:
        issues.append("CredentialSpec.help_url is empty (users need this to get credentials)")
    if spec.direct_api_key_supported and not spec.api_key_instructions:
        issues.append(
            "CredentialSpec.api_key_instructions is empty but direct_api_key_supported=True"
        )

    # 3. Check health check
    if not spec.health_check_endpoint:
        issues.append(
            "CredentialSpec.health_check_endpoint is empty. "
            "Add a lightweight API endpoint for credential validation."
        )
    else:
        checker = HEALTH_CHECKERS.get(credential_name)
        if checker is None:
            issues.append(
                f"No entry in HEALTH_CHECKERS for '{credential_name}'. "
                f"The OAuthBearerHealthChecker fallback will be used. "
                f"Add a dedicated checker if auth is not Bearer token."
            )
        else:
            checker_endpoint = getattr(checker, "ENDPOINT", None) or getattr(
                checker, "endpoint", None
            )
            if checker_endpoint and spec.health_check_endpoint:
                spec_base = spec.health_check_endpoint.split("?")[0]
                checker_base = str(checker_endpoint).split("?")[0]
                if spec_base != checker_base:
                    issues.append(
                        f"Endpoint mismatch: spec='{spec.health_check_endpoint}' "
                        f"vs checker='{checker_endpoint}'"
                    )

    return issues
