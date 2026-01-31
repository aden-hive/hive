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

    def update_message(
        self,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Update an existing message."""
        body: dict[str, Any] = {
            "channel": channel,
            "ts": ts,
            "text": text,
        }
        if blocks:
            body["blocks"] = blocks

        response = httpx.post(
            f"{SLACK_API_BASE}/chat.update",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_message(self, channel: str, ts: str) -> dict[str, Any]:
        """Delete a message."""
        response = httpx.post(
            f"{SLACK_API_BASE}/chat.delete",
            headers=self._headers,
            json={"channel": channel, "ts": ts},
            timeout=30.0,
        )
        return self._handle_response(response)

    def schedule_message(
        self,
        channel: str,
        text: str,
        post_at: int,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Schedule a message for future delivery."""
        body: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "post_at": post_at,
        }
        if thread_ts:
            body["thread_ts"] = thread_ts

        response = httpx.post(
            f"{SLACK_API_BASE}/chat.scheduleMessage",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_channel(
        self,
        name: str,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Create a new channel."""
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.create",
            headers=self._headers,
            json={"name": name, "is_private": is_private},
            timeout=30.0,
        )
        return self._handle_response(response)

    def archive_channel(self, channel: str) -> dict[str, Any]:
        """Archive a channel."""
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.archive",
            headers=self._headers,
            json={"channel": channel},
            timeout=30.0,
        )
        return self._handle_response(response)

    def invite_to_channel(self, channel: str, users: str) -> dict[str, Any]:
        """Invite users to a channel (comma-separated user IDs)."""
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.invite",
            headers=self._headers,
            json={"channel": channel, "users": users},
            timeout=30.0,
        )
        return self._handle_response(response)

    def remove_reaction(
        self,
        channel: str,
        timestamp: str,
        name: str,
    ) -> dict[str, Any]:
        """Remove a reaction emoji from a message."""
        body = {
            "channel": channel,
            "timestamp": timestamp,
            "name": name.strip(":"),
        }
        response = httpx.post(
            f"{SLACK_API_BASE}/reactions.remove",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_users(self, limit: int = 100) -> dict[str, Any]:
        """List users in the workspace."""
        response = httpx.get(
            f"{SLACK_API_BASE}/users.list",
            headers=self._headers,
            params={"limit": min(limit, 1000)},
            timeout=30.0,
        )
        return self._handle_response(response)

    def upload_file(
        self,
        channels: str,
        content: str,
        filename: str,
        title: str | None = None,
        initial_comment: str | None = None,
    ) -> dict[str, Any]:
        """Upload a text file to channels using the new API (files.getUploadURLExternal).
        
        Note: The old files.upload API was deprecated in March 2024.
        """
        content_bytes = content.encode('utf-8')
        length = len(content_bytes)
        
        # Step 1: Get upload URL
        params = {
            "filename": filename,
            "length": length,
        }
        url_response = httpx.get(
            f"{SLACK_API_BASE}/files.getUploadURLExternal",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        url_result = self._handle_response(url_response)
        if "error" in url_result:
            return url_result
        
        upload_url = url_result.get("upload_url")
        file_id = url_result.get("file_id")
        
        if not upload_url or not file_id:
            return {"error": "Failed to get upload URL from Slack"}
        
        # Step 2: Upload file content to the URL
        upload_response = httpx.post(
            upload_url,
            content=content_bytes,
            headers={"Content-Type": "application/octet-stream"},
            timeout=60.0,
        )
        if upload_response.status_code != 200:
            return {"error": f"File upload failed: {upload_response.status_code}"}
        
        # Step 3: Complete the upload
        complete_body: dict[str, Any] = {
            "files": [{"id": file_id, "title": title or filename}],
        }
        if channels:
            complete_body["channel_id"] = channels
        if initial_comment:
            complete_body["initial_comment"] = initial_comment
            
        complete_response = httpx.post(
            f"{SLACK_API_BASE}/files.completeUploadExternal",
            headers=self._headers,
            json=complete_body,
            timeout=30.0,
        )
        result = self._handle_response(complete_response)
        if "error" in result:
            return result
            
        # Return in same format as old API for compatibility
        files = result.get("files", [])
        if files:
            return {"ok": True, "file": files[0]}
        return {"ok": True}


    def set_channel_topic(self, channel: str, topic: str) -> dict[str, Any]:
        """Set the topic for a channel."""
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.setTopic",
            headers=self._headers,
            json={"channel": channel, "topic": topic},
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

    # --- Update/Delete Messages ---

    @mcp.tool()
    def slack_update_message(
        channel: str,
        ts: str,
        text: str,
    ) -> dict:
        """
        Update an existing Slack message.

        Args:
            channel: Channel ID where the message is
            ts: Message timestamp (ts) to update
            text: New message text

        Returns:
            Dict with updated message details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.update_message(channel, ts, text)
            if "error" in result:
                return result
            return {
                "success": True,
                "channel": result.get("channel"),
                "ts": result.get("ts"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_delete_message(channel: str, ts: str) -> dict:
        """
        Delete a Slack message.

        Args:
            channel: Channel ID where the message is
            ts: Message timestamp (ts) to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_message(channel, ts)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Scheduled Messages ---

    @mcp.tool()
    def slack_schedule_message(
        channel: str,
        text: str,
        post_at: int,
        thread_ts: str | None = None,
    ) -> dict:
        """
        Schedule a message for future delivery.

        Args:
            channel: Channel ID to post to
            text: Message text
            post_at: Unix timestamp when to post (must be in the future)
            thread_ts: Optional thread timestamp to reply in a thread

        Returns:
            Dict with scheduled message ID or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.schedule_message(channel, text, post_at, thread_ts)
            if "error" in result:
                return result
            return {
                "success": True,
                "scheduled_message_id": result.get("scheduled_message_id"),
                "post_at": result.get("post_at"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Channel Management ---

    @mcp.tool()
    def slack_create_channel(
        name: str,
        is_private: bool = False,
    ) -> dict:
        """
        Create a new Slack channel.

        Args:
            name: Channel name (lowercase, no spaces, use hyphens)
            is_private: If True, create a private channel

        Returns:
            Dict with new channel details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.create_channel(name, is_private)
            if "error" in result:
                return result
            channel = result.get("channel", {})
            return {
                "success": True,
                "channel": {
                    "id": channel.get("id"),
                    "name": channel.get("name"),
                    "is_private": channel.get("is_private", False),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_archive_channel(channel: str) -> dict:
        """
        Archive a Slack channel.

        Args:
            channel: Channel ID to archive

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.archive_channel(channel)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_invite_to_channel(channel: str, user_ids: str) -> dict:
        """
        Invite users to a Slack channel.

        Args:
            channel: Channel ID
            user_ids: Comma-separated user IDs (e.g., 'U001,U002')

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.invite_to_channel(channel, user_ids)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_set_channel_topic(channel: str, topic: str) -> dict:
        """
        Set the topic for a Slack channel.

        Args:
            channel: Channel ID
            topic: New topic text

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.set_channel_topic(channel, topic)
            if "error" in result:
                return result
            return {"success": True, "topic": result.get("topic")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Reactions ---

    @mcp.tool()
    def slack_remove_reaction(
        channel: str,
        timestamp: str,
        emoji: str,
    ) -> dict:
        """
        Remove an emoji reaction from a message.

        Args:
            channel: Channel ID where the message is
            timestamp: Message timestamp (ts)
            emoji: Emoji name without colons (e.g., 'thumbsup')

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.remove_reaction(channel, timestamp, emoji)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Users ---

    @mcp.tool()
    def slack_list_users(limit: int = 100) -> dict:
        """
        List users in the Slack workspace.

        Args:
            limit: Maximum number of users to return (1-1000, default 100)

        Returns:
            Dict with list of users or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_users(limit)
            if "error" in result:
                return result
            users = [
                {
                    "id": u.get("id"),
                    "name": u.get("name"),
                    "real_name": u.get("real_name"),
                    "is_admin": u.get("is_admin", False),
                    "is_bot": u.get("is_bot", False),
                }
                for u in result.get("members", [])
                if not u.get("deleted", False)
            ]
            return {
                "success": True,
                "users": users,
                "count": len(users),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Files ---

    @mcp.tool()
    def slack_upload_file(
        channel: str,
        content: str,
        filename: str,
        title: str | None = None,
        comment: str | None = None,
    ) -> dict:
        """
        Upload a text file to a Slack channel.

        Args:
            channel: Channel ID to upload to
            content: Text content of the file
            filename: Filename (e.g., 'report.txt', 'data.csv')
            title: Optional title for the file
            comment: Optional comment to post with the file

        Returns:
            Dict with file details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.upload_file(channel, content, filename, title, comment)
            if "error" in result:
                return result
            file_info = result.get("file", {})
            return {
                "success": True,
                "file": {
                    "id": file_info.get("id"),
                    "name": file_info.get("name"),
                    "title": file_info.get("title"),
                    "permalink": file_info.get("permalink"),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

