"""
Brevo Tool - Send transactional emails, SMS, and manage contacts via Brevo API.

Supports:
- API Key authentication (BREVO_API_KEY)

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
    """Internal client wrapping Brevo API calls."""

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
        """Handle Brevo API response."""
        if response.status_code == 401:
            return {"error": "Invalid Brevo API key"}
        if response.status_code == 403:
            return {"error": "Access forbidden - check API key permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code not in (200, 201, 204):
            return {"error": f"HTTP error {response.status_code}: {response.text}"}
        if response.status_code == 204 or not response.content:
            return {"success": True}
        return response.json()

    def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        from_email: str,
        from_name: str,
        text_content: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email."""
        body: dict[str, Any] = {
            "sender": {"email": from_email, "name": from_name},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content,
        }
        if text_content:
            body["textContent"] = text_content

        response = httpx.post(
            f"{BREVO_API_BASE}/smtp/email",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_sms(
        self,
        to: str,
        content: str,
        sender: str,
    ) -> dict[str, Any]:
        """Send a transactional SMS."""
        body = {
            "sender": sender,
            "recipient": to,
            "content": content,
        }
        response = httpx.post(
            f"{BREVO_API_BASE}/transactionalSMS/sms",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_contact(
        self,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        list_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a new contact."""
        attributes: dict[str, Any] = {}
        if first_name:
            attributes["FIRSTNAME"] = first_name
        if last_name:
            attributes["LASTNAME"] = last_name
        if phone:
            attributes["SMS"] = phone

        body: dict[str, Any] = {
            "email": email,
            "attributes": attributes,
        }
        if list_ids:
            body["listIds"] = list_ids

        response = httpx.post(
            f"{BREVO_API_BASE}/contacts",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_contact(self, email: str) -> dict[str, Any]:
        """Get a contact by email."""
        response = httpx.get(
            f"{BREVO_API_BASE}/contacts/{email}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_contact(
        self,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        list_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Update an existing contact."""
        attributes: dict[str, Any] = {}
        if first_name:
            attributes["FIRSTNAME"] = first_name
        if last_name:
            attributes["LASTNAME"] = last_name
        if phone:
            attributes["SMS"] = phone

        body: dict[str, Any] = {"attributes": attributes}
        if list_ids:
            body["listIds"] = list_ids

        response = httpx.put(
            f"{BREVO_API_BASE}/contacts/{email}",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_email_stats(self, message_id: str) -> dict[str, Any]:
        """Get delivery stats for a sent email."""
        response = httpx.get(
            f"{BREVO_API_BASE}/smtp/emails/{message_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: "CredentialStoreAdapter | None" = None,
) -> None:
    """Register Brevo tools with the MCP server."""

    def _get_api_key() -> str | None:
        if credentials is not None:
            key = credentials.get("brevo")
            if key is not None and not isinstance(key, str):
                raise TypeError(
                    f"Expected string from credentials, got {type(key).__name__}"
                )
            return key
        return os.getenv("BREVO_API_KEY")

    def _get_client() -> _BrevoClient | dict[str, str]:
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Brevo credentials not configured",
                "help": (
                    "Set BREVO_API_KEY environment variable or configure via credential store. "
                    "Get your API key at https://app.brevo.com/settings/keys/api"
                ),
            }
        return _BrevoClient(api_key)

    @mcp.tool()
    def brevo_send_email(
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        from_email: str,
        from_name: str,
        text_content: str | None = None,
    ) -> dict:
        """
        Send a transactional email via Brevo.

        Args:
            to_email: Recipient email address
            to_name: Recipient display name
            subject: Email subject line
            html_content: HTML body of the email
            from_email: Sender email address (must be verified in Brevo)
            from_name: Sender display name
            text_content: Optional plain text version of the email

        Returns:
            Dict with message ID or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not to_email or "@" not in to_email:
            return {"error": "Invalid recipient email address"}
        if not subject:
            return {"error": "Email subject cannot be empty"}
        if not html_content:
            return {"error": "Email content cannot be empty"}
        try:
            result = client.send_email(
                to_email, to_name, subject, html_content, from_email, from_name, text_content
            )
            if "error" in result:
                return result
            return {
                "success": True,
                "message_id": result.get("messageId"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_send_sms(
        to: str,
        content: str,
        sender: str,
    ) -> dict:
        """
        Send a transactional SMS via Brevo.

        Args:
            to: Recipient phone number in international format (e.g. '+919876543210')
            content: SMS message content (max 160 characters for single SMS)
            sender: Sender name or number (max 11 alphanumeric characters)

        Returns:
            Dict with success status and reference or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not to.startswith("+"):
            return {"error": "Phone number must be in international format starting with '+'"}
        if not content:
            return {"error": "SMS content cannot be empty"}
        if len(content) > 640:
            return {"error": "SMS content too long (max 640 characters)"}
        try:
            result = client.send_sms(to, content, sender)
            if "error" in result:
                return result
            return {
                "success": True,
                "reference": result.get("reference"),
                "remaining_credits": result.get("remainingCredits"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_create_contact(
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        list_ids: str | None = None,
    ) -> dict:
        """
        Create a new contact in Brevo.

        Args:
            email: Contact email address
            first_name: Optional first name
            last_name: Optional last name
            phone: Optional phone number in international format
            list_ids: Optional comma-separated list IDs to add contact to (e.g. '2,5,8')

        Returns:
            Dict with new contact ID or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not email or "@" not in email:
            return {"error": "Invalid email address"}
        parsed_list_ids = None
        if list_ids:
            try:
                parsed_list_ids = [int(x.strip()) for x in list_ids.split(",")]
            except ValueError:
                return {"error": "list_ids must be comma-separated integers (e.g. '2,5,8')"}
        try:
            result = client.create_contact(email, first_name, last_name, phone, parsed_list_ids)
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "email": email,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_get_contact(email: str) -> dict:
        """
        Retrieve a contact from Brevo by email address.

        Args:
            email: Contact email address to look up

        Returns:
            Dict with contact details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not email or "@" not in email:
            return {"error": "Invalid email address"}
        try:
            result = client.get_contact(email)
            if "error" in result:
                return result
            attributes = result.get("attributes", {})
            return {
                "success": True,
                "id": result.get("id"),
                "email": result.get("email"),
                "first_name": attributes.get("FIRSTNAME"),
                "last_name": attributes.get("LASTNAME"),
                "phone": attributes.get("SMS"),
                "list_ids": result.get("listIds", []),
                "email_blacklisted": result.get("emailBlacklisted", False),
                "sms_blacklisted": result.get("smsBlacklisted", False),
                "created_at": result.get("createdAt"),
                "modified_at": result.get("modifiedAt"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_update_contact(
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        list_ids: str | None = None,
    ) -> dict:
        """
        Update an existing contact in Brevo.

        Args:
            email: Email address of the contact to update
            first_name: Updated first name
            last_name: Updated last name
            phone: Updated phone number in international format
            list_ids: Comma-separated list IDs to add contact to (e.g. '2,5,8')

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not email or "@" not in email:
            return {"error": "Invalid email address"}
        parsed_list_ids = None
        if list_ids:
            try:
                parsed_list_ids = [int(x.strip()) for x in list_ids.split(",")]
            except ValueError:
                return {"error": "list_ids must be comma-separated integers (e.g. '2,5,8')"}
        try:
            result = client.update_contact(email, first_name, last_name, phone, parsed_list_ids)
            if "error" in result:
                return result
            return {"success": True, "email": email}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def brevo_get_email_stats(message_id: str) -> dict:
        """
        Get delivery statistics for a sent transactional email.

        Args:
            message_id: The message ID returned when the email was sent

        Returns:
            Dict with delivery status and events or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not message_id:
            return {"error": "message_id cannot be empty"}
        try:
            result = client.get_email_stats(message_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "message_id": result.get("messageId"),
                "email": result.get("email"),
                "subject": result.get("subject"),
                "date": result.get("date"),
                "events": result.get("events", []),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}