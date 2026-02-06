"""Discord Bot API integration tools for Aden Hive."""

import logging
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DiscordMessage(BaseModel):
    """Discord message model."""
    id: str
    content: str
    author: str
    channel_id: str
    timestamp: str
    reactions: list[str] = Field(default_factory=list)


class DiscordChannel(BaseModel):
    """Discord channel model."""
    id: str
    name: str
    type: str
    guild_id: str | None = None


class _DiscordClient:
    """Internal Discord client wrapper."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = "https://discord.com/api/v10"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

    def send_message(
        self, channel_id: str, content: str, embed: dict | None = None
    ) -> dict[str, Any]:
        """Send message to Discord channel."""
        payload: dict[str, Any] = {"content": content}
        if embed:
            payload["embeds"] = [embed]

        response = httpx.post(
            f"{self.base_url}/channels/{channel_id}/messages",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )

        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text}"}

        return response.json()

    def read_messages(self, channel_id: str, limit: int = 10) -> list[DiscordMessage]:
        """Read messages from Discord channel."""
        response = httpx.get(
            f"{self.base_url}/channels/{channel_id}/messages",
            headers=self._headers,
            params={"limit": limit},
            timeout=30.0,
        )

        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {response.text}")

        messages = []
        for msg in response.json():
            reactions = [r["emoji"]["name"] for r in msg.get("reactions", [])]
            messages.append(DiscordMessage(
                id=msg["id"],
                content=msg.get("content", ""),
                author=msg["author"].get("username", "unknown"),
                channel_id=msg["channel_id"],
                timestamp=msg["timestamp"],
                reactions=reactions
            ))

        return messages

    def list_channels(self, guild_id: str) -> list[DiscordChannel]:
        """List Discord channels in guild."""
        response = httpx.get(
            f"{self.base_url}/guilds/{guild_id}/channels",
            headers=self._headers,
            timeout=30.0,
        )

        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {response.text}")

        channels = []
        for ch in response.json():
            channels.append(DiscordChannel(
                id=ch["id"],
                name=ch.get("name", "unknown"),
                type=str(ch.get("type", 0)),
                guild_id=guild_id
            ))

        return channels

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> bool:
        """Add reaction to Discord message."""
        import urllib.parse
        emoji_encoded = urllib.parse.quote(emoji)

        response = httpx.put(
            f"{self.base_url}/channels/{channel_id}/messages/{message_id}/reactions/{emoji_encoded}/@me",
            headers=self._headers,
            timeout=30.0,
        )

        if response.status_code not in (204, 200):
            raise ValueError(f"HTTP {response.status_code}: {response.text}")

        return True


def register_tools(
    mcp: FastMCP,
    credentials: Any = None,
) -> None:
    """Register Discord tools with FastMCP server."""

    def _get_token() -> str | None:
        """Get Discord bot token from credentials or environment."""
        if credentials is not None:
            token = credentials.get("discord")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('discord'), "
                    f"got {type(token).__name__}"
                )
            return token
        return os.getenv("DISCORD_BOT_TOKEN")

    def _get_client() -> _DiscordClient | dict:
        """Get Discord client or return error dict."""
        token = _get_token()
        if not token:
            return {
                "error": "Discord credentials not configured",
                "help": (
                    "Set DISCORD_BOT_TOKEN environment variable or "
                    "configure via credential store"
                ),
            }
        return _DiscordClient(token)

    @mcp.tool()
    def discord_send_message(
        channel_id: str,
        content: str,
        embed_title: str | None = None,
        embed_description: str | None = None,
        embed_color: int | None = None
    ) -> dict:
        """
        Send a message to a Discord channel.

        Args:
            channel_id: Discord channel ID
            content: Message content
            embed_title: Optional embed title
            embed_description: Optional embed description
            embed_color: Optional embed color (integer)

        Returns:
            Dict with message_id and success status
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            embed = None
            if embed_title or embed_description:
                embed = {}
                if embed_title:
                    embed["title"] = embed_title
                if embed_description:
                    embed["description"] = embed_description
                if embed_color:
                    embed["color"] = embed_color

            result = client.send_message(channel_id, content, embed)

            if "error" in result:
                return result

            return {
                "success": True,
                "message_id": result.get("id"),
                "channel_id": channel_id
            }

        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def discord_read_messages(
        channel_id: str,
        limit: int = 10
    ) -> dict:
        """
        Read recent messages from a Discord channel.

        Args:
            channel_id: Discord channel ID
            limit: Number of messages to retrieve (max 100)

        Returns:
            Dict with messages list and metadata
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            if limit > 100:
                limit = 100

            messages = client.read_messages(channel_id, limit)

            return {
                "success": True,
                "messages": [msg.model_dump() for msg in messages],
                "count": len(messages),
                "channel_id": channel_id
            }

        except Exception as e:
            logger.error(f"Failed to read Discord messages: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def discord_list_channels(
        guild_id: str,
        channel_type: str | None = None
    ) -> dict:
        """
        List Discord channels in a guild.

        Args:
            guild_id: Discord guild (server) ID
            channel_type: Optional channel type filter

        Returns:
            Dict with channels list and metadata
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            channels = client.list_channels(guild_id)

            if channel_type:
                channels = [ch for ch in channels if ch.type == channel_type]

            return {
                "success": True,
                "channels": [ch.model_dump() for ch in channels],
                "count": len(channels),
                "guild_id": guild_id
            }

        except Exception as e:
            logger.error(f"Failed to list Discord channels: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def discord_add_reaction(
        channel_id: str,
        message_id: str,
        emoji: str
    ) -> dict:
        """
        Add a reaction to a Discord message.

        Args:
            channel_id: Discord channel ID
            message_id: Discord message ID
            emoji: Emoji to add (Unicode or custom emoji name)

        Returns:
            Dict with success status
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            success = client.add_reaction(channel_id, message_id, emoji)

            return {
                "success": success,
                "channel_id": channel_id,
                "message_id": message_id,
                "emoji": emoji
            }

        except Exception as e:
            logger.error(f"Failed to add Discord reaction: {e}")
            return {"success": False, "error": str(e)}
