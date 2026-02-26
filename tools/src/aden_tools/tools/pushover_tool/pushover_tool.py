"""
Pushover Tool - Send push notifications to mobile devices via Pushover API.

Supports:
- Sending notifications with title, message, and priority
- Sending notifications with a URL attachment
- Retrieving available sounds
- Authentication via User Key + API Token

API Reference: https://pushover.net/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

PUSHOVER_API_BASE = "https://api.pushover.net/1"


class _PushoverClient:
    """Internal client wrapping Pushover API calls."""

    def __init__(self, token: str, user_key: str):
        self._token = token
        self._user_key = user_key

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Pushover API response."""
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code not in (200, 201):
            return {"error": f"HTTP error {response.status_code}: {response.text}"}
        data = response.json()
        if data.get("status") != 1:
            errors = data.get("errors", ["Unknown error"])
            return {"error": ", ".join(errors)}
        return data

    def send_notification(
        self,
        message: str,
        title: str | None = None,
        priority: int = 0,
        sound: str | None = None,
        device: str | None = None,
    ) -> dict[str, Any]:
        """Send a push notification."""
        body: dict[str, Any] = {
            "token": self._token,
            "user": self._user_key,
            "message": message,
            "priority": priority,
        }
        if title:
            body["title"] = title
        if sound:
            body["sound"] = sound
        if device:
            body["device"] = device
        if priority == 2:
            body["retry"] = 30
            body["expire"] = 3600
        response = httpx.post(
            f"{PUSHOVER_API_BASE}/messages.json",
            data=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_notification_with_url(
        self,
        message: str,
        url: str,
        url_title: str | None = None,
        title: str | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Send a push notification with a URL attachment."""
        body: dict[str, Any] = {
            "token": self._token,
            "user": self._user_key,
            "message": message,
            "url": url,
            "priority": priority,
        }
        if title:
            body["title"] = title
        if url_title:
            body["url_title"] = url_title
        response = httpx.post(
            f"{PUSHOVER_API_BASE}/messages.json",
            data=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_sounds(self) -> dict[str, Any]:
        """Get list of available notification sounds."""
        response = httpx.get(
            f"{PUSHOVER_API_BASE}/sounds.json",
            params={"token": self._token},
            timeout=30.0,
        )
        return self._handle_response(response)

    def validate_user(self, device: str | None = None) -> dict[str, Any]:
        """Validate a user key and optionally a device name."""
        body: dict[str, Any] = {
            "token": self._token,
            "user": self._user_key,
        }
        if device:
            body["device"] = device
        response = httpx.post(
            f"{PUSHOVER_API_BASE}/users/validate.json",
            data=body,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Pushover tools with the MCP server."""

    def _get_credentials() -> tuple[str, str] | None:
        """Get Pushover token and user key from credential store or environment."""
        if credentials is not None:
            token = credentials.get("pushover_token")
            user_key = credentials.get("pushover_user_key")
            if token and user_key:
                return str(token), str(user_key)
        token = os.getenv("PUSHOVER_API_TOKEN")
        user_key = os.getenv("PUSHOVER_USER_KEY")
        if token and user_key:
            return token, user_key
        return None

    def _get_client() -> _PushoverClient | dict[str, str]:
        """Get a Pushover client, or return an error dict if no credentials."""
        creds = _get_credentials()
        if not creds:
            return {
                "error": "Pushover credentials not configured",
                "help": (
                    "Set PUSHOVER_API_TOKEN and PUSHOVER_USER_KEY environment variables "
                    "or configure via credential store"
                ),
            }
        return _PushoverClient(token=creds[0], user_key=creds[1])

    @mcp.tool()
    def pushover_send_notification(
        message: str,
        title: str | None = None,
        priority: int = 0,
        sound: str | None = None,
        device: str | None = None,
    ) -> dict:
        """
        Send a push notification to a mobile device via Pushover.

        Args:
            message: The notification message body
            title: Optional notification title
            priority: Message priority:
                      -2 = lowest (no sound/vibration)
                      -1 = low (no sound/vibration)
                       0 = normal (default)
                       1 = high (bypass quiet hours)
                       2 = emergency (repeats until acknowledged)
            sound: Optional sound name (use pushover_get_sounds to list available)
            device: Optional device name to target a specific device

        Returns:
            Dict with request token or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if priority not in (-2, -1, 0, 1, 2):
            return {"error": "priority must be -2, -1, 0, 1, or 2"}
        try:
            result = client.send_notification(message, title, priority, sound, device)
            if "error" in result:
                return result
            return {
                "success": True,
                "request": result.get("request"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def pushover_send_notification_with_url(
        message: str,
        url: str,
        url_title: str | None = None,
        title: str | None = None,
        priority: int = 0,
    ) -> dict:
        """
        Send a push notification with a URL attachment via Pushover.

        Args:
            message: The notification message body
            url: URL to attach to the notification
            url_title: Optional title for the URL link
            title: Optional notification title
            priority: Message priority (-2 to 2, default 0)

        Returns:
            Dict with request token or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if priority not in (-2, -1, 0, 1, 2):
            return {"error": "priority must be -2, -1, 0, 1, or 2"}
        try:
            result = client.send_notification_with_url(
                message, url, url_title, title, priority
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "request": result.get("request"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def pushover_get_sounds() -> dict:
        """
        Get list of available notification sounds for Pushover.

        Returns:
            Dict with sound names and descriptions or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_sounds()
            if "error" in result:
                return result
            return {
                "success": True,
                "sounds": result.get("sounds", {}),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def pushover_validate_user(device: str | None = None) -> dict:
        """
        Validate Pushover credentials and optionally a specific device.

        Args:
            device: Optional device name to validate

        Returns:
            Dict with validation status and registered devices or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.validate_user(device)
            if "error" in result:
                return result
            return {
                "success": True,
                "devices": result.get("devices", []),
                "licenses": result.get("licenses", []),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
