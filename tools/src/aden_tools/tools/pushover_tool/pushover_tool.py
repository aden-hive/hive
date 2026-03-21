"""
Pushover Tool - Send push notifications to mobile devices and desktops.

Supports:
- Application API token + User key authentication
- Priority levels from lowest (-2) to emergency (2)
- Sounds, HTML formatting, URLs, and TTL

API Reference: https://pushover.net/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

PUSHOVER_API = "https://api.pushover.net/1"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("pushover")
    return os.getenv("PUSHOVER_API_TOKEN")


def _auth_error() -> dict[str, Any]:
    return {
        "error": "PUSHOVER_API_TOKEN not set",
        "help": "Create an app at https://pushover.net/apps/build to get a token",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Pushover tools with the MCP server."""

    @mcp.tool()
    def pushover_send(
        user_key: str,
        message: str,
        title: str = "",
        priority: int = 0,
        sound: str = "",
        device: str = "",
        url: str = "",
        url_title: str = "",
        html: bool = False,
        ttl: int = 0,
    ) -> dict[str, Any]:
        """
        Send a push notification via Pushover.

        Args:
            user_key: Pushover user or group key (30 chars)
            message: Notification body (max 1024 chars)
            title: Notification title (max 250 chars, defaults to app name)
            priority: -2 (lowest), -1 (quiet), 0 (normal), 1 (high), 2 (emergency)
            sound: Notification sound name (use pushover_list_sounds to see options)
            device: Target device name, or comma-separated for multiple
            url: Supplementary URL (max 512 chars)
            url_title: Title for the URL (max 100 chars)
            html: Enable HTML formatting in message body
            ttl: Time-to-live in seconds (0 = no expiry)

        Returns:
            Dict with status and request id. For emergency priority, includes receipt id.
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not user_key or not message:
            return {"error": "user_key and message are required"}
        if len(message) > 1024:
            return {"error": "message must be 1024 characters or fewer"}
        if priority not in (-2, -1, 0, 1, 2):
            return {"error": "priority must be -2, -1, 0, 1, or 2"}

        data: dict[str, Any] = {
            "token": token,
            "user": user_key,
            "message": message,
        }
        if title:
            data["title"] = title[:250]
        if priority != 0:
            data["priority"] = priority
        if priority == 2:
            data["retry"] = 60
            data["expire"] = 3600
        if sound:
            data["sound"] = sound
        if device:
            data["device"] = device
        if url:
            data["url"] = url[:512]
        if url_title:
            data["url_title"] = url_title[:100]
        if html:
            data["html"] = 1
        if ttl > 0:
            data["ttl"] = ttl

        try:
            resp = httpx.post(f"{PUSHOVER_API}/messages.json", data=data, timeout=30.0)
            result = resp.json()
            if result.get("status") != 1:
                errors = result.get("errors", [])
                return {
                    "error": f"Pushover error: {', '.join(errors) if errors else resp.text[:300]}"
                }
            out: dict[str, Any] = {"status": "sent", "request": result.get("request", "")}
            if "receipt" in result:
                out["receipt"] = result["receipt"]
            return out
        except httpx.TimeoutException:
            return {"error": "Request to Pushover timed out"}
        except Exception as e:
            return {"error": f"Pushover request failed: {e!s}"}

    @mcp.tool()
    def pushover_validate_user(
        user_key: str,
        device: str = "",
    ) -> dict[str, Any]:
        """
        Validate a Pushover user or group key.

        Args:
            user_key: Pushover user or group key to validate
            device: Optional device name to validate

        Returns:
            Dict with is_valid flag, devices list, and group flag
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not user_key:
            return {"error": "user_key is required"}

        data: dict[str, str] = {"token": token, "user": user_key}
        if device:
            data["device"] = device

        try:
            resp = httpx.post(f"{PUSHOVER_API}/users/validate.json", data=data, timeout=30.0)
            result = resp.json()
            return {
                "is_valid": result.get("status") == 1,
                "devices": result.get("devices", []),
                "is_group": result.get("group", 0) == 1,
            }
        except Exception as e:
            return {"error": f"Validation failed: {e!s}"}

    @mcp.tool()
    def pushover_list_sounds() -> dict[str, Any]:
        """
        List available notification sounds.

        Returns:
            Dict with sounds mapping (identifier -> description)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        try:
            resp = httpx.get(
                f"{PUSHOVER_API}/sounds.json",
                params={"token": token},
                timeout=30.0,
            )
            result = resp.json()
            if result.get("status") != 1:
                return {"error": f"Failed to list sounds: {resp.text[:300]}"}
            return {"sounds": result.get("sounds", {})}
        except Exception as e:
            return {"error": f"List sounds failed: {e!s}"}

    @mcp.tool()
    def pushover_check_receipt(
        receipt: str,
    ) -> dict[str, Any]:
        """
        Check the status of an emergency-priority notification receipt.

        Args:
            receipt: Receipt ID from an emergency-priority pushover_send response

        Returns:
            Dict with acknowledged flag, acknowledged_by, last_delivered_at,
            expired flag, and called_back flag
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not receipt:
            return {"error": "receipt is required"}

        try:
            resp = httpx.get(
                f"{PUSHOVER_API}/receipts/{receipt}.json",
                params={"token": token},
                timeout=30.0,
            )
            result = resp.json()
            if result.get("status") != 1:
                return {"error": f"Receipt check failed: {resp.text[:300]}"}
            return {
                "acknowledged": result.get("acknowledged", 0) == 1,
                "acknowledged_by": result.get("acknowledged_by", ""),
                "acknowledged_at": result.get("acknowledged_at", 0),
                "last_delivered_at": result.get("last_delivered_at", 0),
                "expired": result.get("expired", 0) == 1,
                "called_back": result.get("called_back", 0) == 1,
            }
        except Exception as e:
            return {"error": f"Receipt check failed: {e!s}"}

    @mcp.tool()
    def pushover_cancel_receipt(
        receipt: str,
    ) -> dict[str, Any]:
        """
        Cancel emergency-priority notification retries for a receipt.

        Stops Pushover from continuing to retry delivery of an emergency
        notification before it expires or is acknowledged.

        Args:
            receipt: Receipt ID from an emergency-priority pushover_send response

        Returns:
            Dict with cancellation status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not receipt:
            return {"error": "receipt is required"}

        try:
            resp = httpx.post(
                f"{PUSHOVER_API}/receipts/{receipt}/cancel.json",
                data={"token": token},
                timeout=30.0,
            )
            result = resp.json()
            if result.get("status") != 1:
                return {"error": f"Cancel failed: {resp.text[:300]}"}
            return {"status": "cancelled", "receipt": receipt}
        except httpx.TimeoutException:
            return {"error": "Cancel request timed out"}
        except Exception as e:
            return {"error": f"Cancel failed: {e!s}"}

    @mcp.tool()
    def pushover_send_glance(
        user_key: str,
        title: str = "",
        text: str = "",
        subtext: str = "",
        count: int | None = None,
        percent: int | None = None,
        device: str = "",
    ) -> dict[str, Any]:
        """
        Update Pushover Glance data on a user's device widget.

        Glances display small data updates on smartwatch/widget screens
        without triggering a full notification.

        Args:
            user_key: Pushover user key
            title: Glance title (max 100 chars)
            text: Primary glance text (max 100 chars)
            subtext: Secondary text line (max 100 chars)
            count: Numeric count to display (-999 to 999)
            percent: Percentage value (0-100)
            device: Target device name (optional)

        Returns:
            Dict with glance update status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not user_key:
            return {"error": "user_key is required"}
        if not any([title, text, subtext, count is not None, percent is not None]):
            return {"error": "At least one of title, text, subtext, count, or percent is required"}

        data: dict[str, Any] = {
            "token": token,
            "user": user_key,
        }
        if title:
            data["title"] = title[:100]
        if text:
            data["text"] = text[:100]
        if subtext:
            data["subtext"] = subtext[:100]
        if count is not None:
            data["count"] = max(-999, min(count, 999))
        if percent is not None:
            data["percent"] = max(0, min(percent, 100))
        if device:
            data["device"] = device

        try:
            resp = httpx.post(
                f"{PUSHOVER_API}/glances.json",
                data=data,
                timeout=30.0,
            )
            result = resp.json()
            if result.get("status") != 1:
                errors = result.get("errors", [])
                return {
                    "error": f"Glance error: {', '.join(errors) if errors else resp.text[:300]}"
                }
            return {"status": "updated", "request": result.get("request", "")}
        except httpx.TimeoutException:
            return {"error": "Glance request timed out"}
        except Exception as e:
            return {"error": f"Glance update failed: {e!s}"}

    @mcp.tool()
    def pushover_get_limits() -> dict[str, Any]:
        """
        Get Pushover application message limits and usage.

        Returns the app's monthly message limit, number of messages sent
        this month, and the reset timestamp.

        Returns:
            Dict with limit, remaining, and reset timestamp
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        try:
            resp = httpx.get(
                f"{PUSHOVER_API}/apps/limits.json",
                params={"token": token},
                timeout=30.0,
            )
            result = resp.json()
            if result.get("status") != 1:
                return {"error": f"Limits check failed: {resp.text[:300]}"}
            return {
                "limit": result.get("limit", 0),
                "remaining": result.get("remaining", 0),
                "reset": result.get("reset", 0),
            }
        except httpx.TimeoutException:
            return {"error": "Limits request timed out"}
        except Exception as e:
            return {"error": f"Limits check failed: {e!s}"}
