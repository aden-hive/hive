"""
Slack Tool - Send messages and interact with Slack workspaces via Slack Web API.

Supports:
- Bot tokens (SLACK_BOT_TOKEN)
- OAuth2 tokens via the credential store

API Reference: https://api.slack.com/methods
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

SLACK_API_BASE = "https://slack.com/api"


class _SlackClient:
    """Internal client wrapping Slack Web API calls."""

    def __init__(self, bot_token: str):
        self._token = bot_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Slack API response format."""
        if response.status_code != 200:
            return {"error": f"HTTP error {response.status_code}: {response.text}"}

        data = response.json()

        if not data.get("ok", False):
            error_code = data.get("error", "unknown_error")
            error_messages = {
                "invalid_auth": "Invalid Slack bot token",
                "token_revoked": "Slack bot token has been revoked",
                "channel_not_found": "Channel not found or bot is not a member",
                "not_in_channel": "Bot is not a member of this channel",
                "is_archived": "Channel is archived",
                "msg_too_long": "Message text is too long",
                "ratelimited": "Rate limit exceeded. Try again later.",
                "missing_scope": f"Missing required scope: {data.get('needed', 'unknown')}",
            }
            return {
                "error": error_messages.get(error_code, f"Slack API error: {error_code}"),
                "error_code": error_code,
            }

        return data

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Send a message to a channel."""
        body: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            body["thread_ts"] = thread_ts
        if blocks:
            body["blocks"] = blocks

        response = httpx.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_conversations(
        self,
        types: str = "public_channel,private_channel",
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List channels in the workspace."""
        params: dict[str, Any] = {
            "types": types,
            "limit": min(limit, 1000),
            "exclude_archived": True,
        }
        if cursor:
            params["cursor"] = cursor

        response = httpx.get(
            f"{SLACK_API_BASE}/conversations.list",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_history(
        self,
        channel: str,
        limit: int = 20,
        oldest: str | None = None,
        latest: str | None = None,
    ) -> dict[str, Any]:
        """Get message history from a channel."""
        params: dict[str, Any] = {
            "channel": channel,
            "limit": min(limit, 1000),
        }
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        response = httpx.get(
            f"{SLACK_API_BASE}/conversations.history",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_reaction(
        self,
        channel: str,
        timestamp: str,
        name: str,
    ) -> dict[str, Any]:
        """Add a reaction emoji to a message."""
        body = {
            "channel": channel,
            "timestamp": timestamp,
            "name": name.strip(":"),  # Remove colons if present
        }
        response = httpx.post(
            f"{SLACK_API_BASE}/reactions.add",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a user."""
        response = httpx.get(
            f"{SLACK_API_BASE}/users.info",
            headers=self._headers,
            params={"user": user_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    def auth_test(self) -> dict[str, Any]:
        """Test authentication and get bot info."""
        response = httpx.post(
            f"{SLACK_API_BASE}/auth.test",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: "CredentialStoreAdapter | None" = None,
) -> None:
    """Register Slack tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Slack bot token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("slack")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('slack'), got {type(token).__name__}"
                )
            return token
        return os.getenv("SLACK_BOT_TOKEN")

    def _get_client() -> _SlackClient | dict[str, str]:
        """Get a Slack client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Slack credentials not configured",
                "help": (
                    "Set SLACK_BOT_TOKEN environment variable "
                    "or configure via credential store"
                ),
            }
        return _SlackClient(token)

    # --- Messages ---

    @mcp.tool()
    def slack_send_message(
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict:
        """
        Send a message to a Slack channel.

        Args:
            channel: Channel ID (e.g., 'C0123456789') or channel name (e.g., '#general')
            text: Message text (supports Slack markdown/mrkdwn)
            thread_ts: Optional thread timestamp to reply in a thread

        Returns:
            Dict with message details (ts, channel) or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.post_message(channel, text, thread_ts)
            if "error" in result:
                return result
            return {
                "success": True,
                "channel": result.get("channel"),
                "ts": result.get("ts"),
                "message": result.get("message", {}),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Channels ---

    @mcp.tool()
    def slack_list_channels(
        types: str = "public_channel,private_channel",
        limit: int = 100,
    ) -> dict:
        """
        List channels in the Slack workspace.

        Args:
            types: Comma-separated channel types
                   (public_channel, private_channel, mpim, im)
            limit: Maximum number of channels to return (1-1000, default 100)

        Returns:
            Dict with list of channels or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_conversations(types, limit)
            if "error" in result:
                return result
            channels = [
                {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_private": ch.get("is_private", False),
                    "num_members": ch.get("num_members", 0),
                    "topic": ch.get("topic", {}).get("value", ""),
                }
                for ch in result.get("channels", [])
            ]
            return {
                "success": True,
                "channels": channels,
                "count": len(channels),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- History ---

    @mcp.tool()
    def slack_get_channel_history(
        channel: str,
        limit: int = 20,
    ) -> dict:
        """
        Get recent messages from a Slack channel.

        Args:
            channel: Channel ID (e.g., 'C0123456789')
            limit: Maximum number of messages to return (1-1000, default 20)

        Returns:
            Dict with list of messages or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_history(channel, limit)
            if "error" in result:
                return result
            messages = [
                {
                    "ts": msg.get("ts"),
                    "user": msg.get("user"),
                    "text": msg.get("text"),
                    "type": msg.get("type"),
                    "thread_ts": msg.get("thread_ts"),
                }
                for msg in result.get("messages", [])
            ]
            return {
                "success": True,
                "messages": messages,
                "count": len(messages),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Reactions ---

    @mcp.tool()
    def slack_add_reaction(
        channel: str,
        timestamp: str,
        emoji: str,
    ) -> dict:
        """
        Add an emoji reaction to a message.

        Args:
            channel: Channel ID where the message is
            timestamp: Message timestamp (ts) to react to
            emoji: Emoji name without colons (e.g., 'thumbsup', 'white_check_mark')

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.add_reaction(channel, timestamp, emoji)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Users ---

    @mcp.tool()
    def slack_get_user_info(user_id: str) -> dict:
        """
        Get information about a Slack user.

        Args:
            user_id: User ID (e.g., 'U0123456789')

        Returns:
            Dict with user profile information or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_user_info(user_id)
            if "error" in result:
                return result
            user = result.get("user", {})
            profile = user.get("profile", {})
            return {
                "success": True,
                "user": {
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "real_name": user.get("real_name"),
                    "email": profile.get("email"),
                    "title": profile.get("title"),
                    "is_admin": user.get("is_admin", False),
                    "is_bot": user.get("is_bot", False),
                    "tz": user.get("tz"),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
