"""
WhatsApp Cloud API Tool - Send messages via the Meta WhatsApp Business Cloud API.

Supports:
- Text messages (within 24h conversation window)
- Template messages (for initiating conversations)
- Image and document media messages
- Read receipts and reactions
- Template discovery

API Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/reference
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GRAPH_API_BASE = "https://graph.facebook.com/v25.0"


class _WhatsAppClient:
    """Internal client wrapping WhatsApp Cloud API calls."""

    def __init__(self, access_token: str, phone_number_id: str):
        self._token = access_token
        self._phone_number_id = phone_number_id

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @property
    def _messages_url(self) -> str:
        return f"{GRAPH_API_BASE}/{self._phone_number_id}/messages"

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle WhatsApp Cloud API response format."""
        if response.status_code == 401:
            return {"error": "Invalid or expired WhatsApp access token"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}

        try:
            data = response.json()
        except Exception:
            if response.status_code != 200:
                return {"error": f"HTTP error {response.status_code}: {response.text}"}
            return {"error": "Invalid JSON response from WhatsApp API"}

        if "error" in data:
            err = data["error"]
            code = err.get("code", 0)
            msg = err.get("message", "Unknown error")
            error_map = {
                100: f"Invalid parameter: {msg}",
                190: "Access token expired or invalid",
                368: "Temporarily blocked for policy violations",
                131030: "Recipient phone number not on WhatsApp",
                131047: "Re-engagement message requires a template (24h window expired)",
                131051: "Unsupported message type",
            }
            friendly = error_map.get(code, f"WhatsApp API error ({code}): {msg}")
            return {"error": friendly, "error_code": code}

        if response.status_code >= 400:
            return {"error": f"HTTP error {response.status_code}: {response.text}"}

        return data

    def send_message(self, to: str, body: str) -> dict[str, Any]:
        """Send a text message."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        response = httpx.post(
            self._messages_url,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        components: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Send a pre-approved template message."""
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language},
        }
        if components:
            template["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        response = httpx.post(
            self._messages_url,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_templates(self, waba_id: str, limit: int = 20) -> dict[str, Any]:
        """List message templates for the WhatsApp Business Account."""
        url = f"{GRAPH_API_BASE}/{waba_id}/message_templates"
        params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        response = httpx.get(
            url,
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def mark_as_read(self, message_id: str) -> dict[str, Any]:
        """Mark an incoming message as read (blue ticks)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        response = httpx.post(
            self._messages_url,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_reaction(self, to: str, message_id: str, emoji: str) -> dict[str, Any]:
        """React to a message with an emoji."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }
        response = httpx.post(
            self._messages_url,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_media(
        self,
        to: str,
        media_type: str,
        media_url: str,
        caption: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Send a media message (image, document, video, audio)."""
        media_obj: dict[str, Any] = {"link": media_url}
        if caption:
            media_obj["caption"] = caption
        if filename and media_type == "document":
            media_obj["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_obj,
        }
        response = httpx.post(
            self._messages_url,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register WhatsApp Cloud API tools with the MCP server."""

    def _get_token() -> str | None:
        if credentials is not None:
            token = credentials.get("whatsapp")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('whatsapp'), got {type(token).__name__}"
                )
            return token
        return os.getenv("WHATSAPP_ACCESS_TOKEN")

    def _get_phone_number_id() -> str | None:
        if credentials is not None:
            val = credentials.get("whatsapp_phone_number_id")
            if val is not None and not isinstance(val, str):
                raise TypeError(
                    f"Expected string from credentials.get('whatsapp_phone_number_id'), "
                    f"got {type(val).__name__}"
                )
            return val
        return os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    def _get_client() -> _WhatsAppClient | dict[str, str]:
        token = _get_token()
        phone_id = _get_phone_number_id()
        if not token or not phone_id:
            return {
                "error": "WhatsApp credentials not configured",
                "help": (
                    "Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID "
                    "environment variables or configure via credential store"
                ),
            }
        return _WhatsAppClient(token, phone_id)

    # --- Text Messaging ---

    @mcp.tool()
    def whatsapp_send_message(to: str, body: str) -> dict:
        """
        Send a text message via WhatsApp.

        Note: Free-form text messages can only be sent within a 24-hour window
        after the recipient last messaged you. To initiate a conversation,
        use whatsapp_send_template instead.

        Args:
            to: Recipient phone number in E.164 format (e.g., '+14155552671')
            body: Message text (max 4096 characters)

        Returns:
            Dict with message ID and status, or error
        """
        if not to or not body:
            return {"error": "to and body are required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.send_message(to, body)
            if "error" in result:
                return result
            messages = result.get("messages", [])
            return {
                "success": True,
                "message_id": messages[0]["id"] if messages else None,
                "to": to,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Template Messages ---

    @mcp.tool()
    def whatsapp_send_template(
        to: str,
        template_name: str,
        language: str = "en",
        components: str = "",
    ) -> dict:
        """
        Send a pre-approved template message via WhatsApp.

        Template messages are required for initiating conversations (outside
        the 24-hour window). Templates must be pre-approved in the Meta
        Business dashboard before use.

        Args:
            to: Recipient phone number in E.164 format (e.g., '+14155552671')
            template_name: Name of the approved template (e.g., 'hello_world')
            language: Template language code (default 'en')
            components: Optional JSON string of template components for
                personalization, e.g.:
                '[{"type":"body","parameters":[{"type":"text","text":"John"}]}]'

        Returns:
            Dict with message ID and status, or error
        """
        if not to or not template_name:
            return {"error": "to and template_name are required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            parsed_components = None
            if components:
                try:
                    parsed_components = json.loads(components)
                except json.JSONDecodeError as e:
                    return {"error": f"Invalid components JSON: {e}"}

            result = client.send_template(to, template_name, language, parsed_components)
            if "error" in result:
                return result
            messages = result.get("messages", [])
            return {
                "success": True,
                "message_id": messages[0]["id"] if messages else None,
                "to": to,
                "template": template_name,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Template Discovery ---

    @mcp.tool()
    def whatsapp_list_templates(
        waba_id: str,
        limit: int = 20,
    ) -> dict:
        """
        List approved message templates for your WhatsApp Business Account.

        Use this to discover available templates before sending them with
        whatsapp_send_template.

        Args:
            waba_id: WhatsApp Business Account ID (find in Meta Business settings)
            limit: Maximum number of templates to return (1-100, default 20)

        Returns:
            Dict with list of templates including name, status, language, and category
        """
        if not waba_id:
            return {"error": "waba_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_templates(waba_id, limit)
            if "error" in result:
                return result
            templates = [
                {
                    "name": t.get("name"),
                    "status": t.get("status"),
                    "language": t.get("language"),
                    "category": t.get("category"),
                    "id": t.get("id"),
                }
                for t in result.get("data", [])
            ]
            return {
                "success": True,
                "templates": templates,
                "count": len(templates),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Read Receipts ---

    @mcp.tool()
    def whatsapp_mark_as_read(message_id: str) -> dict:
        """
        Mark an incoming WhatsApp message as read (shows blue ticks to sender).

        Args:
            message_id: The WhatsApp message ID to mark as read
                (from webhook payload, e.g., 'wamid.xxx')

        Returns:
            Dict with success status or error
        """
        if not message_id:
            return {"error": "message_id is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.mark_as_read(message_id)
            if "error" in result:
                return result
            return {"success": result.get("success", True)}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Reactions ---

    @mcp.tool()
    def whatsapp_send_reaction(to: str, message_id: str, emoji: str) -> dict:
        """
        React to a WhatsApp message with an emoji.

        Args:
            to: Recipient phone number in E.164 format (e.g., '+14155552671')
            message_id: The WhatsApp message ID to react to
                (e.g., 'wamid.xxx')
            emoji: The emoji character to react with (e.g., '\U0001f44d' for thumbs up)

        Returns:
            Dict with success status or error
        """
        if not to or not message_id or not emoji:
            return {"error": "to, message_id and emoji are required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.send_reaction(to, message_id, emoji)
            if "error" in result:
                return result
            messages = result.get("messages", [])
            return {
                "success": True,
                "message_id": messages[0]["id"] if messages else None,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Media Messages ---

    @mcp.tool()
    def whatsapp_send_image(
        to: str,
        image_url: str,
        caption: str = "",
    ) -> dict:
        """
        Send an image message via WhatsApp.

        Args:
            to: Recipient phone number in E.164 format (e.g., '+14155552671')
            image_url: Public URL of the image (JPEG or PNG, max 5MB)
            caption: Optional caption for the image

        Returns:
            Dict with message ID or error
        """
        if not to or not image_url:
            return {"error": "to and image_url are required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.send_media(to, "image", image_url, caption=caption or None)
            if "error" in result:
                return result
            messages = result.get("messages", [])
            return {
                "success": True,
                "message_id": messages[0]["id"] if messages else None,
                "to": to,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def whatsapp_send_document(
        to: str,
        document_url: str,
        filename: str = "",
        caption: str = "",
    ) -> dict:
        """
        Send a document (PDF, etc.) via WhatsApp.

        Args:
            to: Recipient phone number in E.164 format (e.g., '+14155552671')
            document_url: Public URL of the document (max 100MB)
            filename: Display filename for the document (e.g., 'report.pdf')
            caption: Optional caption for the document

        Returns:
            Dict with message ID or error
        """
        if not to or not document_url:
            return {"error": "to and document_url are required"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.send_media(
                to,
                "document",
                document_url,
                caption=caption or None,
                filename=filename or None,
            )
            if "error" in result:
                return result
            messages = result.get("messages", [])
            return {
                "success": True,
                "message_id": messages[0]["id"] if messages else None,
                "to": to,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
