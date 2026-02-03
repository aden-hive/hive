"""
Slack Tool - Manage channels, messages, and users via Slack API.

Supports:
- Bot User OAuth Token (SLACK_BOT_TOKEN) via the credential store
- Uses slack-sdk for API interactions

API Reference: https://api.slack.com/methods
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _SlackClient:
    """Internal client wrapping Slack SDK calls."""

    def __init__(self, token: str):
        self.client = WebClient(token=token)

    def _handle_error(self, e: SlackApiError) -> dict[str, Any]:
        """Handle Slack API errors."""
        return {"error": f"Slack API error: {e.response['error']}"}

    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to a channel."""
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
            )
            return response.data  # type: ignore
        except SlackApiError as e:
            return self._handle_error(e)

    def list_channels(
        self,
        limit: int = 100,
        types: str = "public_channel",
        exclude_archived: bool = True,
    ) -> dict[str, Any]:
        """List channels in the workspace."""
        try:
            response = self.client.conversations_list(
                limit=limit,
                types=types,
                exclude_archived=exclude_archived,
            )
            return response.data  # type: ignore
        except SlackApiError as e:
            return self._handle_error(e)

    def get_channel_history(
        self,
        channel: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get conversation history."""
        try:
            response = self.client.conversations_history(
                channel=channel,
                limit=limit,
            )
            return response.data  # type: ignore
        except SlackApiError as e:
            return self._handle_error(e)

    def list_users(
        self,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List users in the workspace."""
        try:
            response = self.client.users_list(limit=limit)
            return response.data  # type: ignore
        except SlackApiError as e:
            return self._handle_error(e)

    def get_user(
        self,
        user_id: str,
    ) -> dict[str, Any]:
        """Get info about a specific user."""
        try:
            response = self.client.users_info(user=user_id)
            return response.data  # type: ignore
        except SlackApiError as e:
            return self._handle_error(e)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
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

    # --- Messaging ---

    @mcp.tool()
    def slack_send_message(
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict:
        """
        Send a message to a Slack channel.

        Args:
            channel: Channel ID or name (e.g., "C12345678" or "#general")
            text: Message text
            thread_ts: Optional thread timestamp to reply to a thread

        Returns:
            Dict with response data or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.send_message(channel, text, thread_ts)

    # --- Channels ---

    @mcp.tool()
    def slack_list_channels(
        limit: int = 20,
        exclude_archived: bool = True,
    ) -> dict:
        """
        List public Slack channels.

        Args:
            limit: Maximum number of channels to return (default 20)
            exclude_archived: Whether to exclude archived channels (default True)

        Returns:
            Dict with channels list or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.list_channels(limit, exclude_archived=exclude_archived)

    @mcp.tool()
    def slack_get_channel_history(
        channel: str,
        limit: int = 10,
    ) -> dict:
        """
        Get recent messages from a channel.

        Args:
            channel: Channel ID (e.g., "C12345678")
            limit: Number of messages to retrieve (default 10)

        Returns:
            Dict with messages history or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.get_channel_history(channel, limit)

    # --- Users ---

    @mcp.tool()
    def slack_list_users(
        limit: int = 20,
    ) -> dict:
        """
        List users in the workspace.

        Args:
            limit: Maximum number of users to return (default 20)

        Returns:
            Dict with users list or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.list_users(limit)

    @mcp.tool()
    def slack_get_user(
        user_id: str,
    ) -> dict:
        """
        Get details for a specific user.

        Args:
            user_id: User ID (e.g., "U12345678")

        Returns:
            Dict with user info or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.get_user(user_id)
