"""
Telegram Bot Tool - Send messages and documents via Telegram Bot API.

Supports:
- Bot API tokens (TELEGRAM_BOT_TOKEN)

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
