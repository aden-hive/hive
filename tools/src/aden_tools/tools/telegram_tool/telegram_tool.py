"""
Telegram Bot Tool - Send messages, documents, photos via Telegram Bot API.
Security: Token from credentials or env only, no hardcoding.
"""
from __future__ import annotations
import os
from typing import TYPE_CHECKING, Any, Literal
import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

class _TelegramClient:
    """Internal Telegram Bot API client with rate-limit awareness."""
    def __init__(self, bot_token: str):
        self._token = bot_token
        self._client = httpx.Client(
            base_url=f"{TELEGRAM_API_BASE}{bot_token}",
            timeout=httpx.Timeout(15.0, connect=10.0, read=30.0),
            follow_redirects=True,
        )

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 200:
            return response.json()

        error_data = response.json() if response.content else {}
        description = error_data.get("description", response.text or "Unknown error")

        match response.status_code:
            case 401:
                return {"error": "Invalid or revoked Telegram bot token"}
            case 403:
                return {"error": "Bot blocked by user or lacks permissions"}
            case 404:
                return {"error": "Chat or file not found"}
            case 429:
                return {"error": "Rate limit exceeded - wait and retry"}
            case 400:
                return {"error": f"Bad request: {description}"}
            case _ if response.status_code >= 500:
                return {"error": f"Telegram server error (HTTP {response.status_code})"}
            case _:
                return {"error": f"Unexpected error (HTTP {response.status_code}): {description}"}

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: Literal["HTML", "MarkdownV2", ""] | None = None,
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_notification": disable_notification,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = self._client.post("/sendMessage", json=payload)
            return self._handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network failure: {str(e)}"}

    def send_document(
        self,
        chat_id: str | int,
        document: str,              # file_id or https URL
        caption: str | None = None,
        parse_mode: Literal["HTML", "MarkdownV2", ""] | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        payload = {"chat_id": chat_id}
        files = None

        if document.startswith(("http://", "https://")):
            payload["document"] = document
        else:
            # assume file_id
            payload["document"] = document

        if caption:
            payload["caption"] = caption[:1024]
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if filename:
            payload["file_name"] = filename

        try:
            resp = self._client.post("/sendDocument", json=payload, files=files)
            return self._handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network failure: {str(e)}"}

    def send_photo(
        self,
        chat_id: str | int,
        photo: str,                 # file_id or https URL
        caption: str | None = None,
        parse_mode: Literal["HTML", "MarkdownV2", ""] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "chat_id": chat_id,
            "photo": photo,
        }
        if caption:
            payload["caption"] = caption[:1024]
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = self._client.post("/sendPhoto", json=payload)
            return self._handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network failure: {str(e)}"}

    def get_me(self) -> dict[str, Any]:
        try:
            resp = self._client.get("/getMe")
            return self._handle_response(resp)
        except httpx.RequestError as e:
            return {"error": f"Failed to get bot info: {str(e)}"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Telegram tools with the MCP server."""

    def _get_token() -> str | None:
        if credentials:
            token = credentials.get("telegram")
            if token and not isinstance(token, str):
                raise TypeError(f"Invalid token type: {type(token)}")
            return token
        return os.getenv("TELEGRAM_BOT_TOKEN")

    def _get_client() -> _TelegramClient | dict[str, str]:
        token = _get_token()
        if not token:
            return {
                "error": "Telegram bot token missing",
                "help": "Set TELEGRAM_BOT_TOKEN env var or add via credential store. Get token from @BotFather."
            }
        return _TelegramClient(token)

    @mcp.tool()
    def telegram_send_message(
        chat_id: str | int,
        text: str,
        parse_mode: Literal["HTML", "MarkdownV2", ""] = "",
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
    ) -> dict[str, Any]:
        """Send text message to Telegram chat/user/group."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        return client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode or None,
            disable_notification=disable_notification,
            disable_web_page_preview=disable_web_page_preview,
        )

    @mcp.tool()
    def telegram_send_document(
        chat_id: str | int,
        document: str,
        caption: str = "",
        parse_mode: Literal["HTML", "MarkdownV2", ""] = "",
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Send document (PDF, CSV, ZIP, etc) by URL or file_id."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        return client.send_document(
            chat_id=chat_id,
            document=document,
            caption=caption or None,
            parse_mode=parse_mode or None,
            filename=filename,
        )

    @mcp.tool()
    def telegram_send_photo(
        chat_id: str | int,
        photo: str,
        caption: str = "",
        parse_mode: Literal["HTML", "MarkdownV2", ""] = "",
    ) -> dict[str, Any]:
        """Send photo by URL or file_id."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        return client.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption or None,
            parse_mode=parse_mode or None,
        )

    @mcp.tool()
    def telegram_bot_info() -> dict[str, Any]:
        """Verify bot is working - returns bot username, id, etc."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.get_me()
