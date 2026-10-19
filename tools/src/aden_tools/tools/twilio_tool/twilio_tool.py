"""
Twilio Tool - SMS and WhatsApp messaging via Twilio REST API.

Supports:
- Account SID + Auth Token (Basic auth)
- Send SMS, send WhatsApp, list messages, get message

API Reference: https://www.twilio.com/docs/messaging/api/message-resource
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (account_sid, auth_token)."""
    if credentials is not None:
        sid = credentials.get("twilio_sid")
        token = credentials.get("twilio_token")
        return sid, token
    return os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")


def _base_url(account_sid: str) -> str:
    return f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"


def _auth_header(account_sid: str, auth_token: str) -> str:
    encoded = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    return f"Basic {encoded}"


def _request(method: str, url: str, account_sid: str, auth_token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a request to the Twilio API."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = _auth_header(account_sid, auth_token)
    try:
        resp = getattr(httpx, method)(
            url,
            headers=headers,
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Twilio credentials."}
        if resp.status_code == 404:
            return {"error": "Resource not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201):
            return {"error": f"Twilio API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Twilio timed out"}
    except Exception as e:
        return {"error": f"Twilio request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN not set",
        "help": "Get credentials from https://console.twilio.com/",
    }


def _extract_message(msg: dict) -> dict[str, Any]:
    return {
        "sid": msg.get("sid", ""),
        "to": msg.get("to", ""),
        "from": msg.get("from", ""),
        "body": msg.get("body", ""),
        "status": msg.get("status", ""),
        "direction": msg.get("direction", ""),
        "date_sent": msg.get("date_sent"),
        "price": msg.get("price"),
        "error_code": msg.get("error_code"),
        "error_message": msg.get("error_message"),
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Twilio tools with the MCP server."""

    @mcp.tool()
    def twilio_send_sms(
        to: str,
        from_number: str,
        body: str,
    ) -> dict[str, Any]:
        """
        Send an SMS message via Twilio.

        Args:
            to: Recipient phone number in E.164 format e.g. "+14155552671" (required)
            from_number: Sender Twilio phone number in E.164 format (required)
            body: Message text, up to 1600 characters (required)

        Returns:
            Dict with message details (sid, status, to, from)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()
        if not to or not from_number or not body:
            return {"error": "to, from_number, and body are required"}

        url = f"{_base_url(sid)}/Messages.json"
        data = _request(
            "post",
            url,
            sid,
            token,
            data={"To": to, "From": from_number, "Body": body},
        )
        if "error" in data:
            return data

        return _extract_message(data)

    @mcp.tool()
    def twilio_send_whatsapp(
        to: str,
        from_number: str,
        body: str,
    ) -> dict[str, Any]:
        """
        Send a WhatsApp message via Twilio.

        Args:
            to: Recipient phone in E.164 format e.g. "+14155552671"
                (required, whatsapp: prefix added automatically)
            from_number: Sender Twilio WhatsApp number in E.164
                format (required, whatsapp: prefix added
                automatically)
            body: Message text (required)

        Returns:
            Dict with message details (sid, status, to, from)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()
        if not to or not from_number or not body:
            return {"error": "to, from_number, and body are required"}

        wa_to = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        wa_from = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"

        url = f"{_base_url(sid)}/Messages.json"
        data = _request(
            "post",
            url,
            sid,
            token,
            data={"To": wa_to, "From": wa_from, "Body": body},
        )
        if "error" in data:
            return data

        return _extract_message(data)

    @mcp.tool()
    def twilio_list_messages(
        to: str = "",
        from_number: str = "",
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        List recent messages from your Twilio account.

        Args:
            to: Filter by recipient number (optional)
            from_number: Filter by sender number (optional)
            page_size: Number of results (1-1000, default 20)

        Returns:
            Dict with messages list (sid, to, from, body, status)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()

        url = f"{_base_url(sid)}/Messages.json"
        params: dict[str, Any] = {"PageSize": max(1, min(page_size, 1000))}
        if to:
            params["To"] = to
        if from_number:
            params["From"] = from_number

        data = _request("get", url, sid, token, params=params)
        if "error" in data:
            return data

        messages = [_extract_message(m) for m in data.get("messages", [])]
        return {"messages": messages, "count": len(messages)}

    @mcp.tool()
    def twilio_get_message(message_sid: str) -> dict[str, Any]:
        """
        Get details about a specific Twilio message.

        Args:
            message_sid: Message SID e.g. "SMxxxxxxxx" (required)

        Returns:
            Dict with message details (sid, to, from, body, status, price)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()
        if not message_sid:
            return {"error": "message_sid is required"}

        url = f"{_base_url(sid)}/Messages/{message_sid}.json"
        data = _request("get", url, sid, token)
        if "error" in data:
            return data

        return _extract_message(data)

    @mcp.tool()
    def twilio_list_phone_numbers() -> dict[str, Any]:
        """
        List phone numbers owned by the Twilio account.

        Returns:
            Dict with phone numbers list (sid, phone_number, friendly_name, capabilities)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()

        url = f"{_base_url(sid)}/IncomingPhoneNumbers.json"
        data = _request("get", url, sid, token, params={"PageSize": 100})
        if "error" in data:
            return data

        numbers = []
        for n in data.get("incoming_phone_numbers", []):
            caps = n.get("capabilities", {})
            numbers.append(
                {
                    "sid": n.get("sid", ""),
                    "phone_number": n.get("phone_number", ""),
                    "friendly_name": n.get("friendly_name", ""),
                    "sms_enabled": caps.get("sms", False),
                    "voice_enabled": caps.get("voice", False),
                    "mms_enabled": caps.get("mms", False),
                    "date_created": n.get("date_created"),
                }
            )
        return {"phone_numbers": numbers, "count": len(numbers)}

    @mcp.tool()
    def twilio_list_calls(
        to: str = "",
        from_number: str = "",
        status: str = "",
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        List recent calls from your Twilio account.

        Args:
            to: Filter by recipient number (optional)
            from_number: Filter by caller number (optional)
            status: Filter by status: queued, ringing, in-progress, completed,
                    busy, failed, no-answer, canceled (optional)
            page_size: Number of results (1-1000, default 20)

        Returns:
            Dict with calls list (sid, to, from, status, duration, price)
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()

        url = f"{_base_url(sid)}/Calls.json"
        params: dict[str, Any] = {"PageSize": max(1, min(page_size, 1000))}
        if to:
            params["To"] = to
        if from_number:
            params["From"] = from_number
        if status:
            params["Status"] = status

        data = _request("get", url, sid, token, params=params)
        if "error" in data:
            return data

        calls = []
        for c in data.get("calls", []):
            calls.append(
                {
                    "sid": c.get("sid", ""),
                    "to": c.get("to", ""),
                    "from": c.get("from", ""),
                    "status": c.get("status", ""),
                    "direction": c.get("direction", ""),
                    "duration": c.get("duration"),
                    "price": c.get("price"),
                    "start_time": c.get("start_time"),
                    "end_time": c.get("end_time"),
                }
            )
        return {"calls": calls, "count": len(calls)}

    @mcp.tool()
    def twilio_delete_message(message_sid: str) -> dict[str, Any]:
        """
        Delete a message from Twilio.

        Args:
            message_sid: Message SID e.g. "SMxxxxxxxx" (required)

        Returns:
            Dict with success status or error
        """
        sid, token = _get_credentials(credentials)
        if not sid or not token:
            return _auth_error()
        if not message_sid:
            return {"error": "message_sid is required"}

        url = f"{_base_url(sid)}/Messages/{message_sid}.json"
        headers: dict[str, str] = {}
        headers["Authorization"] = _auth_header(sid, token)
        try:
            resp = httpx.delete(url, headers=headers, timeout=30.0)
            if resp.status_code == 204:
                return {"sid": message_sid, "status": "deleted"}
            if resp.status_code == 401:
                return {"error": "Unauthorized. Check your Twilio credentials."}
            if resp.status_code == 404:
                return {"error": "Message not found."}
            return {"error": f"Twilio API error {resp.status_code}: {resp.text[:500]}"}
        except httpx.TimeoutException:
            return {"error": "Request to Twilio timed out"}
        except Exception as e:
            return {"error": f"Twilio request failed: {e!s}"}
