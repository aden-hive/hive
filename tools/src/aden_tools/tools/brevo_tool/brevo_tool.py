"""
Brevo Tool - Send transactional emails, SMS, and manage contacts via Brevo API.

Supports:
- Transactional email sending
- Transactional SMS sending
- Contact create/read/update

API Reference: https://developers.brevo.com/reference
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

BREVO_API_BASE = "https://api.brevo.com/v3"


class _BrevoClient:
    """Internal client wrapping Brevo API v3 calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Brevo API key"}
        if response.status_code == 400:
            try:
                detail = response.json()
                msg = detail.get("message", response.text)
            except Exception:
                msg = response.text
            return {"error": f"Bad request: {msg}"}
        if response.status_code == 403:
            return {"error": "Brevo API key lacks required permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Brevo API error (HTTP {response.status_code}): {detail}"}
        # Success (200, 201, 204)
        if response.status_code == 204:
            return {"success": True}
        try:
            return response.json()
        except Exception:
            return {"success": True}

    def send_email(
        self,
        to: list[dict[str, str]],
        subject: str,
        html_content: str,
        sender: dict[str, str],
        text_content: str | None = None,
        cc: list[dict[str, str]] | None = None,
        bcc: list[dict[str, str]] | None = None,
        reply_to: dict[str, str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email."""
        payload: dict[str, Any] = {
            "to": to,
            "subject": subject,
            "htmlContent": html_content,
            "sender": sender,
        }
        if text_content:
            payload["textContent"] = text_content
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if reply_to:
            payload["replyTo"] = reply_to
        if tags:
            payload["tags"] = tags

        response = httpx.post(
            f"{BREVO_API_BASE}/smtp/email",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_sms(
        self,
        sender: str,
        recipient: str,
        content: str,
        sms_type: str = "transactional",
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional SMS."""
        payload: dict[str, Any] = {
            "sender": sender,
            "recipient": recipient,
            "content": content,
            "type": sms_type,
        }
        if tag:
            payload["tag"] = tag

        response = httpx.post(
            f"{BREVO_API_BASE}/transactionalSMS/send",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_contact(
        self,
        email: str | None = None,
        attributes: dict[str, Any] | None = None,
        list_ids: list[int] | None = None,
        update_enabled: bool = False,
    ) -> dict[str, Any]:
        """Create a new contact."""
        payload: dict[str, Any] = {}
        if email:
            payload["email"] = email
        if attributes:
            payload["attributes"] = attributes
        if list_ids:
            payload["listIds"] = list_ids
        if update_enabled:
            payload["updateEnabled"] = True

        response = httpx.post(
            f"{BREVO_API_BASE}/contacts",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_contact(self, identifier: str) -> dict[str, Any]:
        """Get a contact by email or ID."""
        response = httpx.get(
            f"{BREVO_API_BASE}/contacts/{identifier}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_contact(
        self,
        identifier: str,
        attributes: dict[str, Any] | None = None,
        list_ids: list[int] | None = None,
        unlink_list_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Update a contact."""
        payload: dict[str, Any] = {}
        if attributes:
            payload["attributes"] = attributes
        if list_ids:
            payload["listIds"] = list_ids
        if unlink_list_ids:
            payload["unlinkListIds"] = unlink_list_ids

        response = httpx.put(
            f"{BREVO_API_BASE}/contacts/{identifier}",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Brevo tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Brevo API key from credential store or environment."""
        if credentials is not None:
            key = credentials.get("brevo")
            if key is not None and not isinstance(key, str):
                raise TypeError(
                    f"Expected string from credentials.get('brevo'), got {type(key).__name__}"
                )
            return key
        return os.getenv("BREVO_API_KEY")

    def _get_client() -> _BrevoClient | dict[str, str]:
        """Get a Brevo client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Brevo API key not configured",
                "help": (
                    "Set BREVO_API_KEY environment variable or configure via "
                    "credential store. Get your key at https://app.brevo.com/settings/keys/api"
                ),
            }
        return _BrevoClient(api_key)

    @mcp.tool()
    def brevo_send_email(
        to: list[dict[str, str]],
        subject: str,
        html_content: str,
        sender_email: str,
        sender_name: str = "",
        text_content: str = "",
        cc: list[dict[str, str]] | None = None,
        bcc: list[dict[str, str]] | None = None,
        reply_to_email: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Send a transactional email via Brevo.

        Use this for notifications, alerts, confirmations, or any triggered email.

        Args:
            to: Recipients list. Each item: {"email": "user@example.com", "name": "User Name"}.
                Name is optional.
            subject: Email subject line.
            html_content: Email body as HTML string.
            sender_email: Sender email address (must be a verified sender in Brevo).
            sender_name: Sender display name. Optional.
            text_content: Plain text alternative body. Optional.
            cc: CC recipients. Same format as 'to'. Optional.
            bcc: BCC recipients. Same format as 'to'. Optional.
            reply_to_email: Reply-to email address. Optional.
            tags: Tags for categorizing the email. Optional.

        Returns:
            Dict with messageId on success, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not to:
            return {"error": "At least one recipient is required"}
        if not subject:
            return {"error": "Subject is required"}
        if not html_content:
            return {"error": "HTML content is required"}
        if not sender_email:
            return {"error": "Sender email is required"}

        sender: dict[str, str] = {"email": sender_email}
        if sender_name:
            sender["name"] = sender_name

        reply_to = {"email": reply_to_email} if reply_to_email else None

        try:
            result = client.send_email(
                to=to,
                subject=subject,
                html_content=html_content,
                sender=sender,
                text_content=text_content if text_content else None,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                tags=tags,
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "message_id": result.get("messageId", ""),
                "to": [r.get("email") for r in to],
                "subject": subject,
            }
        except httpx.TimeoutException:
            return {"error": "Brevo request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_send_sms(
        sender: str,
        recipient: str,
        content: str,
        sms_type: str = "transactional",
        tag: str = "",
    ) -> dict[str, Any]:
        """
        Send a transactional SMS via Brevo.

        Use this for SMS notifications, alerts, or verification messages.

        Args:
            sender: Sender name (max 11 alphanumeric chars) or phone number (max 15 digits).
            recipient: Recipient phone number with country code (e.g., "33612345678").
            content: SMS message text. Messages over 160 chars are sent as multiple SMS.
            sms_type: Either "transactional" or "marketing". Defaults to "transactional".
            tag: Optional tag for categorizing the SMS.

        Returns:
            Dict with messageId on success, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not sender:
            return {"error": "Sender is required"}
        if not recipient:
            return {"error": "Recipient phone number is required"}
        if not content:
            return {"error": "SMS content is required"}

        try:
            result = client.send_sms(
                sender=sender,
                recipient=recipient,
                content=content,
                sms_type=sms_type,
                tag=tag if tag else None,
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "message_id": result.get("messageId", ""),
                "recipient": recipient,
            }
        except httpx.TimeoutException:
            return {"error": "Brevo request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_create_contact(
        email: str,
        attributes: dict[str, Any] | None = None,
        list_ids: list[int] | None = None,
        update_enabled: bool = False,
    ) -> dict[str, Any]:
        """
        Create a contact in Brevo.

        Use this to add new contacts to your Brevo account for email/SMS campaigns.

        Args:
            email: Contact email address.
            attributes: Contact attributes in UPPERCASE (e.g., {"FNAME": "John", "LNAME": "Doe"}).
                Standard attributes: FNAME, LNAME, SMS (phone with country code like +33xxxxxxxxxx).
            list_ids: List IDs to add the contact to. Optional.
            update_enabled: If True, updates the contact if it already exists. Defaults to False.

        Returns:
            Dict with contact id on success, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not email:
            return {"error": "Email is required"}

        try:
            result = client.create_contact(
                email=email,
                attributes=attributes,
                list_ids=list_ids,
                update_enabled=update_enabled,
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "email": email,
            }
        except httpx.TimeoutException:
            return {"error": "Brevo request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_get_contact(
        identifier: str,
    ) -> dict[str, Any]:
        """
        Get a contact from Brevo by email address or contact ID.

        Args:
            identifier: Contact email address or numeric contact ID.

        Returns:
            Dict with contact details (email, attributes, listIds, statistics)
            or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not identifier:
            return {"error": "Contact identifier (email or ID) is required"}

        try:
            result = client.get_contact(identifier)
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "email": result.get("email"),
                "attributes": result.get("attributes", {}),
                "list_ids": result.get("listIds", []),
                "email_blacklisted": result.get("emailBlacklisted", False),
                "sms_blacklisted": result.get("smsBlacklisted", False),
            }
        except httpx.TimeoutException:
            return {"error": "Brevo request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_update_contact(
        identifier: str,
        attributes: dict[str, Any] | None = None,
        list_ids: list[int] | None = None,
        unlink_list_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        Update a contact in Brevo.

        Args:
            identifier: Contact email address or numeric contact ID.
            attributes: Attributes to update in UPPERCASE (e.g., {"FNAME": "Jane"}).
            list_ids: List IDs to add the contact to. Optional.
            unlink_list_ids: List IDs to remove the contact from. Optional.

        Returns:
            Dict with success status, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not identifier:
            return {"error": "Contact identifier (email or ID) is required"}

        try:
            result = client.update_contact(
                identifier=identifier,
                attributes=attributes,
                list_ids=list_ids,
                unlink_list_ids=unlink_list_ids,
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "identifier": identifier,
                "message": "Contact updated successfully",
            }
        except httpx.TimeoutException:
            return {"error": "Brevo request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
