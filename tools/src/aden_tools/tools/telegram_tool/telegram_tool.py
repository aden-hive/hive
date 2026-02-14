"""
Telegram Bot Tool - Manage messages, media, and chats via Telegram Bot API.

Supports:
- Bot API tokens (TELEGRAM_BOT_TOKEN)
- Message management (send, edit, delete, forward)
- Media (photos, documents)
- Chat info and actions (get chat, typing indicators)
- Pin management (pin, unpin)

API Reference: https://core.telegram.org/bots/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class _TelegramClient:
    """Internal client wrapping Telegram Bot API calls."""

    def __init__(self, bot_token: str):
        self._token = bot_token

    @property
    def _base_url(self) -> str:
        return f"{TELEGRAM_API_BASE}{self._token}"

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Telegram bot token"}
        if response.status_code == 400:
            try:
                detail = response.json().get("description", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Bad request: {detail}"}
        if response.status_code == 403:
            return {"error": "Bot was blocked by the user or lacks permissions"}
        if response.status_code == 404:
            return {"error": "Chat not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("description", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Telegram API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """Send a text message to a chat."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = httpx.post(
            f"{self._base_url}/sendMessage",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_document(
        self,
        chat_id: str,
        document: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Send a document to a chat."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "document": document,
        }
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = httpx.post(
            f"{self._base_url}/sendDocument",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Edit the text of a previously sent message."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = httpx.post(
            f"{self._base_url}/editMessageText",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_message(
        self,
        chat_id: str,
        message_id: int,
    ) -> dict[str, Any]:
        """Delete a message from a chat."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        response = httpx.post(
            f"{self._base_url}/deleteMessage",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def forward_message(
        self,
        chat_id: str,
        from_chat_id: str,
        message_id: int,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """Forward a message from one chat to another."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
        }
        response = httpx.post(
            f"{self._base_url}/forwardMessage",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_photo(
        self,
        chat_id: str,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Send a photo to a chat via URL or file_id."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo,
        }
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = httpx.post(
            f"{self._base_url}/sendPhoto",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_chat_action(
        self,
        chat_id: str,
        action: str,
    ) -> dict[str, Any]:
        """Send a chat action (e.g. 'typing') to indicate bot activity."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "action": action,
        }
        response = httpx.post(
            f"{self._base_url}/sendChatAction",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def pin_chat_message(
        self,
        chat_id: str,
        message_id: int,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """Pin a message in a chat."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
        }
        response = httpx.post(
            f"{self._base_url}/pinChatMessage",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def unpin_chat_message(
        self,
        chat_id: str,
        message_id: int | None = None,
    ) -> dict[str, Any]:
        """Unpin a message in a chat. If message_id is None, unpins the most recent."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
        }
        if message_id is not None:
            payload["message_id"] = message_id

        response = httpx.post(
            f"{self._base_url}/unpinChatMessage",
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_chat(
        self,
        chat_id: str,
    ) -> dict[str, Any]:
        """Get information about a chat."""
        response = httpx.get(
            f"{self._base_url}/getChat",
            params={"chat_id": chat_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_me(self) -> dict[str, Any]:
        """Get bot information (useful for health checks)."""
        response = httpx.get(
            f"{self._base_url}/getMe",
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Telegram tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Telegram bot token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("telegram")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('telegram'), got {type(token).__name__}"
                )
            return token
        return os.getenv("TELEGRAM_BOT_TOKEN")

    def _get_client() -> _TelegramClient | dict[str, str]:
        """Get a Telegram client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Telegram bot token not configured",
                "help": (
                    "Set TELEGRAM_BOT_TOKEN environment variable or configure via "
                    "credential store. Get your token from @BotFather on Telegram."
                ),
            }
        return _TelegramClient(token)

    @mcp.tool()
    def telegram_send_message(
        chat_id: str,
        text: str,
        parse_mode: str = "",
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """
        Send a message to a Telegram chat.

        Use this to send notifications, alerts, or updates to a Telegram user or group.

        Args:
            chat_id: Target chat ID (numeric) or @username for public channels
            text: Message text (1-4096 characters). Supports HTML/Markdown if parse_mode set.
            parse_mode: Optional format mode - "HTML" or "Markdown". Empty for plain text.
            disable_notification: If True, sends message silently.

        Returns:
            Dict with message info on success, or error dict on failure.
            Success includes: message_id, chat info, date, text.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode if parse_mode else None,
                disable_notification=disable_notification,
            )
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def telegram_send_document(
        chat_id: str,
        document: str,
        caption: str = "",
        parse_mode: str = "",
    ) -> dict[str, Any]:
        """
        Send a document to a Telegram chat.

        Use this to send files like PDFs, CSVs, or other documents.

        Args:
            chat_id: Target chat ID (numeric) or @username for public channels
            document: URL of the document to send, or file_id of existing file on Telegram
            caption: Optional caption for the document (0-1024 characters)
            parse_mode: Optional format mode for caption - "HTML" or "Markdown"

        Returns:
            Dict with message info on success, or error dict on failure.
            Success includes: message_id, document info, chat info.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption if caption else None,
                parse_mode=parse_mode if parse_mode else None,
            )
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Message Management ---

    @mcp.tool()
    def telegram_edit_message(
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "",
    ) -> dict[str, Any]:
        """
        Edit a previously sent message.

        Use this to update the content of a message the bot has already sent.
        Only the bot's own messages can be edited.

        Args:
            chat_id: Chat ID where the message was sent
            message_id: ID of the message to edit
            text: New message text (1-4096 characters). Supports HTML/Markdown if parse_mode set.
            parse_mode: Optional format mode - "HTML" or "Markdown". Empty for plain text.

        Returns:
            Dict with updated message info on success, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode if parse_mode else None,
            )
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def telegram_delete_message(
        chat_id: str,
        message_id: int,
    ) -> dict[str, Any]:
        """
        Delete a message from a Telegram chat.

        Bots can delete their own messages within 48 hours, or any message
        if the bot has delete permissions in the chat.

        Args:
            chat_id: Chat ID where the message is
            message_id: ID of the message to delete

        Returns:
            Dict with success status or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            result = client.delete_message(
                chat_id=chat_id,
                message_id=message_id,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def telegram_forward_message(
        chat_id: str,
        from_chat_id: str,
        message_id: int,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """
        Forward a message from one chat to another.

        The forwarded message will show the original sender attribution.

        Args:
            chat_id: Target chat ID to forward the message to
            from_chat_id: Source chat ID where the original message is
            message_id: ID of the message to forward
            disable_notification: If True, forwards message silently.

        Returns:
            Dict with forwarded message info on success, or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.forward_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                disable_notification=disable_notification,
            )
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Media ---

    @mcp.tool()
    def telegram_send_photo(
        chat_id: str,
        photo: str,
        caption: str = "",
        parse_mode: str = "",
    ) -> dict[str, Any]:
        """
        Send a photo to a Telegram chat.

        Use this to share images like charts, screenshots, or generated visuals.

        Args:
            chat_id: Target chat ID (numeric) or @username for public channels
            photo: URL of the photo to send, or file_id of existing photo on Telegram
            caption: Optional caption for the photo (0-1024 characters)
            parse_mode: Optional format mode for caption - "HTML" or "Markdown"

        Returns:
            Dict with message info on success, or error dict on failure.
            Success includes: message_id, photo info, chat info.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption if caption else None,
                parse_mode=parse_mode if parse_mode else None,
            )
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Chat Actions & Info ---

    @mcp.tool()
    def telegram_send_chat_action(
        chat_id: str,
        action: str = "typing",
    ) -> dict[str, Any]:
        """
        Show a chat action indicator (e.g. "typing...") to the user.

        Use this to indicate the bot is processing a request. The action
        disappears after ~5 seconds or when the bot sends a message.

        Args:
            chat_id: Target chat ID
            action: Action type. One of: "typing", "upload_photo", "upload_document",
                "record_video", "upload_video", "record_voice", "upload_voice",
                "find_location", "choose_sticker".

        Returns:
            Dict with success status or error dict on failure.
        """
        valid_actions = {
            "typing",
            "upload_photo",
            "upload_document",
            "record_video",
            "upload_video",
            "record_voice",
            "upload_voice",
            "find_location",
            "choose_sticker",
        }
        if action not in valid_actions:
            return {
                "error": f"Invalid action: {action!r}",
                "help": f"Must be one of: {', '.join(sorted(valid_actions))}",
            }

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            result = client.send_chat_action(
                chat_id=chat_id,
                action=action,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def telegram_get_chat(
        chat_id: str,
    ) -> dict[str, Any]:
        """
        Get information about a Telegram chat.

        Returns metadata including chat title, type, description, and permissions.

        Args:
            chat_id: Chat ID (numeric) or @username for public channels

        Returns:
            Dict with chat info on success (title, type, description, etc.),
            or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_chat(chat_id=chat_id)
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Pin Management ---

    @mcp.tool()
    def telegram_pin_message(
        chat_id: str,
        message_id: int,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """
        Pin a message in a Telegram chat.

        The bot must have the appropriate admin rights in the chat.

        Args:
            chat_id: Chat ID where the message is
            message_id: ID of the message to pin
            disable_notification: If True, pins silently without notifying members.

        Returns:
            Dict with success status or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            result = client.pin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=disable_notification,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def telegram_unpin_message(
        chat_id: str,
        message_id: int = 0,
    ) -> dict[str, Any]:
        """
        Unpin a message in a Telegram chat.

        If message_id is 0, unpins the most recently pinned message.
        The bot must have the appropriate admin rights in the chat.

        Args:
            chat_id: Chat ID where the pinned message is
            message_id: ID of the message to unpin. Use 0 to unpin the most recent.

        Returns:
            Dict with success status or error dict on failure.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            result = client.unpin_chat_message(
                chat_id=chat_id,
                message_id=message_id if message_id != 0 else None,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Telegram request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
