"""
Discord Tool - Send messages and interact with Discord servers via Discord API.

Supports:
- Bot tokens (DISCORD_BOT_TOKEN)

API Reference: https://discord.com/developers/docs
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_MESSAGE_LENGTH = 2000  # Discord API limit
# Channel types: 0 = GUILD_TEXT, 5 = GUILD_ANNOUNCEMENT (both support messages)
TEXT_CHANNEL_TYPES = (0, 5)
MAX_RETRIES = 2  # 3 total attempts on 429
MAX_RETRY_WAIT = 60  # cap wait at 60s


class _DiscordClient:
    """Internal client wrapping Discord API calls."""

    def __init__(self, bot_token: str):
        self._token = bot_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make HTTP request with retry on 429 rate limit."""
        request_kwargs = {"headers": self._headers, "timeout": 30.0, **kwargs}
        for attempt in range(MAX_RETRIES + 1):
            response = httpx.request(method, url, **request_kwargs)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                try:
                    data = response.json()
                    wait = min(float(data.get("retry_after", 1)), MAX_RETRY_WAIT)
                except Exception:
                    wait = min(2**attempt, MAX_RETRY_WAIT)
                time.sleep(wait)
                continue
            return self._handle_response(response)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Discord API response format."""
        if response.status_code == 204:
            return {"success": True}

        if response.status_code == 429:
            try:
                data = response.json()
                retry_after = data.get("retry_after", 60)
                message = data.get("message", "Rate limit exceeded")
            except Exception:
                retry_after = 60
                message = "Rate limit exceeded"
            return {
                "error": f"Discord rate limit exceeded. Retry after {retry_after}s",
                "retry_after": retry_after,
                "message": message,
            }

        if response.status_code != 200:
            try:
                data = response.json()
                message = data.get("message", response.text)
            except Exception:
                message = response.text
            return {"error": f"HTTP {response.status_code}: {message}"}

        return response.json()

    def list_guilds(self) -> dict[str, Any]:
        """List guilds (servers) the bot is a member of."""
        return self._request_with_retry("GET", f"{DISCORD_API_BASE}/users/@me/guilds")

    def list_channels(self, guild_id: str, text_only: bool = True) -> dict[str, Any]:
        """List channels for a guild. Optionally filter to text channels only."""
        result = self._request_with_retry("GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/channels")
        if isinstance(result, dict) and "error" in result:
            return result
        if text_only:
            result = [c for c in result if c.get("type") in TEXT_CHANNEL_TYPES]
        return result

    def send_message(
        self,
        channel_id: str,
        content: str,
        *,
        tts: bool = False,
    ) -> dict[str, Any]:
        """Send a message to a channel."""
        body: dict[str, Any] = {"content": content, "tts": tts}
        return self._request_with_retry(
            "POST",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            json=body,
        )

    def get_messages(
        self,
        channel_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        """Get recent messages from a channel."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return self._request_with_retry(
            "GET",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            params=params,
        )


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Discord tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get Discord bot token from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("discord", account)
            token = credentials.get("discord")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('discord'), got {type(token).__name__}"
                )
            return token
        return os.getenv("DISCORD_BOT_TOKEN")

    def _get_client(account: str = "") -> _DiscordClient | dict[str, str]:
        """Get a Discord client, or return an error dict if no credentials."""
        token = _get_token(account)
        if not token:
            return {
                "error": "Discord credentials not configured",
                "help": (
                    "Set DISCORD_BOT_TOKEN environment variable or configure via credential store"
                ),
            }
        return _DiscordClient(token)

    @mcp.tool()
    def discord_list_guilds(account: str = "") -> dict:
        """
        List Discord guilds (servers) the bot is a member of.

        Returns guild IDs and names. Use guild IDs with discord_list_channels.

        Returns:
            Dict with list of guilds or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_guilds()
            if "error" in result:
                return result
            return {"guilds": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def discord_list_channels(guild_id: str, text_only: bool = True, account: str = "") -> dict:
        """
        List channels for a Discord guild (server).

        Args:
            guild_id: Guild (server) ID. Enable Developer Mode in Discord and
                       right-click the server to copy ID. Or use discord_list_guilds.
            text_only: If True (default), return only text channels (type 0 and 5).
                       Set False to include voice, category, and other channel types.

        Returns:
            Dict with list of channels or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_channels(guild_id, text_only=text_only)
            if "error" in result:
                return result
            return {"channels": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def discord_send_message(
        channel_id: str,
        content: str,
        tts: bool = False,
        account: str = "",
    ) -> dict:
        """
        Send a message to a Discord channel.

        Args:
            channel_id: Channel ID (right-click channel > Copy ID in Dev Mode)
            content: Message text (max 2000 characters)
            tts: Whether to use text-to-speech

        Returns:
            Dict with message details or error
        """
        if len(content) > MAX_MESSAGE_LENGTH:
            return {
                "error": f"Message exceeds {MAX_MESSAGE_LENGTH} character limit",
                "max_length": MAX_MESSAGE_LENGTH,
                "provided": len(content),
            }
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.send_message(channel_id, content, tts=tts)
            if "error" in result:
                return result
            return {"success": True, "message": result}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def discord_get_messages(
        channel_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Get recent messages from a Discord channel.

        Args:
            channel_id: Channel ID
            limit: Max messages to return (1-100, default 50)
            before: Message ID to get messages before (for pagination)
            after: Message ID to get messages after (for pagination)

        Returns:
            Dict with list of messages or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_messages(channel_id, limit=limit, before=before, after=after)
            if "error" in result:
                return result
            return {"messages": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
