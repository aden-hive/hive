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

    def __init__(self, bot_token: str, user_token: str | None = None):
        self._token = bot_token
        self._user_token = user_token  # For search API which requires user tokens

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _user_headers(self) -> dict[str, str]:
        """Headers using user token (for search API)."""
        token = self._user_token or self._token
        return {
            "Authorization": f"Bearer {token}",
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
        content_bytes = content.encode("utf-8")
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

    # --- Advanced Features ---

    def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",
    ) -> dict[str, Any]:
        """Search for messages across the workspace.

        Note: This API requires a User OAuth Token (xoxp-...), not a Bot Token.
        Set SLACK_USER_TOKEN environment variable for this to work.
        """
        # Use user token if available (search requires user token)
        headers = self._user_headers()
        response = httpx.get(
            f"{SLACK_API_BASE}/search.messages",
            headers=headers,
            params={
                "query": query,
                "count": min(count, 100),
                "sort": sort,
                "sort_dir": "desc",
            },
            timeout=30.0,
        )
        result = self._handle_response(response)
        # Add helpful hint if token type error
        if result.get("error_code") == "not_allowed_token_type":
            result["error"] = "Search requires User Token (xoxp-). Set SLACK_USER_TOKEN env var."
            result["help"] = "Get user token from Slack App > OAuth > User OAuth Token"
        return result

    def get_thread_replies(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get all replies in a thread."""
        response = httpx.get(
            f"{SLACK_API_BASE}/conversations.replies",
            headers=self._headers,
            params={
                "channel": channel,
                "ts": thread_ts,
                "limit": min(limit, 1000),
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def pin_message(self, channel: str, timestamp: str) -> dict[str, Any]:
        """Pin a message to a channel."""
        response = httpx.post(
            f"{SLACK_API_BASE}/pins.add",
            headers=self._headers,
            json={"channel": channel, "timestamp": timestamp},
            timeout=30.0,
        )
        return self._handle_response(response)

    def unpin_message(self, channel: str, timestamp: str) -> dict[str, Any]:
        """Unpin a message from a channel."""
        response = httpx.post(
            f"{SLACK_API_BASE}/pins.remove",
            headers=self._headers,
            json={"channel": channel, "timestamp": timestamp},
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_pins(self, channel: str) -> dict[str, Any]:
        """List pinned items in a channel."""
        response = httpx.get(
            f"{SLACK_API_BASE}/pins.list",
            headers=self._headers,
            params={"channel": channel},
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_bookmark(
        self,
        channel: str,
        title: str,
        link: str,
        emoji: str | None = None,
    ) -> dict[str, Any]:
        """Add a bookmark to a channel."""
        body: dict[str, Any] = {
            "channel_id": channel,
            "title": title,
            "type": "link",
            "link": link,
        }
        if emoji:
            body["emoji"] = emoji

        response = httpx.post(
            f"{SLACK_API_BASE}/bookmarks.add",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_scheduled_messages(self, channel: str | None = None) -> dict[str, Any]:
        """List scheduled messages."""
        params: dict[str, Any] = {}
        if channel:
            params["channel"] = channel

        response = httpx.post(
            f"{SLACK_API_BASE}/chat.scheduledMessages.list",
            headers=self._headers,
            json=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_scheduled_message(
        self,
        channel: str,
        scheduled_message_id: str,
    ) -> dict[str, Any]:
        """Delete a scheduled message."""
        response = httpx.post(
            f"{SLACK_API_BASE}/chat.deleteScheduledMessage",
            headers=self._headers,
            json={
                "channel": channel,
                "scheduled_message_id": scheduled_message_id,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def open_dm(self, users: str) -> dict[str, Any]:
        """Open a DM or multi-person DM. Returns channel ID."""
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.open",
            headers=self._headers,
            json={"users": users},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_permalink(self, channel: str, message_ts: str) -> dict[str, Any]:
        """Get a permanent link to a message."""
        response = httpx.get(
            f"{SLACK_API_BASE}/chat.getPermalink",
            headers=self._headers,
            params={"channel": channel, "message_ts": message_ts},
            timeout=30.0,
        )
        return self._handle_response(response)

    def post_ephemeral(
        self,
        channel: str,
        user: str,
        text: str,
        blocks: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Send an ephemeral message visible only to one user."""
        body: dict[str, Any] = {
            "channel": channel,
            "user": user,
            "text": text,
        }
        if blocks:
            body["blocks"] = blocks

        response = httpx.post(
            f"{SLACK_API_BASE}/chat.postEphemeral",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Advanced Features: Views (Modals & Home Tab)
    # ============================================================

    def open_modal(
        self,
        trigger_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Open a modal dialog.

        Args:
            trigger_id: From slash command or button interaction
            view: Modal view definition (type: "modal", title, blocks, etc.)
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/views.open",
            headers=self._headers,
            json={
                "trigger_id": trigger_id,
                "view": view,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_modal(
        self,
        view_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing modal view."""
        response = httpx.post(
            f"{SLACK_API_BASE}/views.update",
            headers=self._headers,
            json={
                "view_id": view_id,
                "view": view,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def push_modal(
        self,
        trigger_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Push a new view onto the modal stack."""
        response = httpx.post(
            f"{SLACK_API_BASE}/views.push",
            headers=self._headers,
            json={
                "trigger_id": trigger_id,
                "view": view,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def publish_home_tab(
        self,
        user_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish/update a user's home tab.

        Args:
            user_id: User whose home tab to update
            view: Home tab view (type: "home", blocks)
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/views.publish",
            headers=self._headers,
            json={
                "user_id": user_id,
                "view": view,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: User Status & Presence
    # ============================================================

    def set_user_status(
        self,
        status_text: str,
        status_emoji: str | None = None,
        expiration: int | None = None,
    ) -> dict[str, Any]:
        """Set the user's status (requires user token with users.profile:write scope).

        Args:
            status_text: Status message text
            status_emoji: Status emoji (e.g., ':palm_tree:')
            expiration: Unix timestamp for status expiration (0 = don't clear)
        """
        profile: dict[str, Any] = {"status_text": status_text}
        if status_emoji:
            profile["status_emoji"] = status_emoji
        if expiration is not None:
            profile["status_expiration"] = expiration

        response = httpx.post(
            f"{SLACK_API_BASE}/users.profile.set",
            headers=self._user_headers(),
            json={"profile": profile},
            timeout=30.0,
        )
        return self._handle_response(response)

    def set_presence(self, presence: str) -> dict[str, Any]:
        """Set user presence (auto or away).

        Args:
            presence: 'auto' or 'away'
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/users.setPresence",
            headers=self._headers,
            json={"presence": presence},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_presence(self, user_id: str) -> dict[str, Any]:
        """Get a user's presence status."""
        response = httpx.get(
            f"{SLACK_API_BASE}/users.getPresence",
            headers=self._headers,
            params={"user": user_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: Reminders
    # ============================================================

    def create_reminder(
        self,
        text: str,
        time: str,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Create a reminder.

        Args:
            text: Reminder text
            time: When to remind (Unix timestamp, or natural language like 'in 5 minutes')
            user: User ID to set reminder for (defaults to authed user)
        """
        body: dict[str, Any] = {"text": text, "time": time}
        if user:
            body["user"] = user

        response = httpx.post(
            f"{SLACK_API_BASE}/reminders.add",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_reminders(self) -> dict[str, Any]:
        """List all reminders for the authenticated user."""
        response = httpx.get(
            f"{SLACK_API_BASE}/reminders.list",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_reminder(self, reminder_id: str) -> dict[str, Any]:
        """Delete a reminder by ID."""
        response = httpx.post(
            f"{SLACK_API_BASE}/reminders.delete",
            headers=self._headers,
            json={"reminder": reminder_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: User Groups
    # ============================================================

    def create_usergroup(
        self,
        name: str,
        handle: str | None = None,
        description: str | None = None,
        channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a user group (for @mentions).

        Args:
            name: Display name for the group
            handle: Short name for @mentioning (defaults to slugified name)
            description: Optional description
            channels: Optional list of channel IDs to associate
        """
        body: dict[str, Any] = {"name": name}
        if handle:
            body["handle"] = handle
        if description:
            body["description"] = description
        if channels:
            body["channels"] = ",".join(channels)

        response = httpx.post(
            f"{SLACK_API_BASE}/usergroups.create",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_usergroup_members(
        self,
        usergroup_id: str,
        users: list[str],
    ) -> dict[str, Any]:
        """Update the members of a user group.

        Args:
            usergroup_id: The ID of the user group
            users: List of user IDs to set as members
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/usergroups.users.update",
            headers=self._headers,
            json={
                "usergroup": usergroup_id,
                "users": ",".join(users),
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_usergroups(self) -> dict[str, Any]:
        """List all user groups in the workspace."""
        response = httpx.get(
            f"{SLACK_API_BASE}/usergroups.list",
            headers=self._headers,
            params={"include_count": True, "include_users": True},
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: Emoji
    # ============================================================

    def list_emoji(self) -> dict[str, Any]:
        """List all custom emoji in the workspace."""
        response = httpx.get(
            f"{SLACK_API_BASE}/emoji.list",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: Canvas (Collaborative Documents)
    # ============================================================

    def create_canvas(
        self,
        title: str,
        document_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new canvas document.

        Args:
            title: Canvas title
            document_content: Optional initial content (markdown structure)
        """
        body: dict[str, Any] = {"title": title}
        if document_content:
            body["document_content"] = document_content

        response = httpx.post(
            f"{SLACK_API_BASE}/canvases.create",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def edit_canvas(
        self,
        canvas_id: str,
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply edits to a canvas.

        Args:
            canvas_id: The canvas document ID
            changes: List of change operations (insert_at_start, insert_at_end, etc.)
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/canvases.edit",
            headers=self._headers,
            json={
                "canvas_id": canvas_id,
                "changes": changes,
            },
            timeout=30.0,
        )
        return self._handle_response(response)

    # ============================================================
    # Phase 2: Analytics (AI-Driven - Pure Data for Agent Intelligence)
    # ============================================================
    #
    # DESIGN: These methods return RAW DATA. The AI agent uses its
    # intelligence to analyze, summarize, find patterns, identify
    # unanswered questions, etc. No rule-based logic here.
    # ============================================================

    def get_messages_for_analysis(
        self,
        channel: str,
        limit: int = 100,
        include_threads: bool = True,
    ) -> dict[str, Any]:
        """Fetch messages with full context for AI analysis.

        Returns raw message data including text, user, reactions,
        thread info, and timestamps. The AI agent should use its
        intelligence to analyze this data for:
        - Activity patterns
        - Unanswered questions
        - Engagement levels
        - Sentiment
        - Key topics

        Args:
            channel: Channel ID to fetch from
            limit: Number of messages (max 100)
            include_threads: Whether to fetch thread replies for messages
        """
        history = self.get_history(channel, limit=min(limit, 100))
        if "error" in history:
            return history

        messages = history.get("messages", [])
        if not messages:
            return {"channel": channel, "messages": [], "count": 0}

        # Enrich messages with structured data for AI analysis
        enriched = []
        for msg in messages:
            enriched_msg = {
                "text": msg.get("text", ""),
                "user": msg.get("user"),
                "ts": msg.get("ts"),
                "is_bot": bool(msg.get("bot_id")),
                "reactions": [
                    {"emoji": r.get("name"), "count": r.get("count", 0)}
                    for r in msg.get("reactions", [])
                ],
                "reply_count": msg.get("reply_count", 0),
                "is_thread_parent": bool(msg.get("thread_ts") and msg.get("reply_count", 0) > 0),
                "is_thread_reply": bool(msg.get("parent_user_id")),
            }

            # Optionally fetch thread replies for deeper analysis
            if include_threads and enriched_msg["reply_count"] > 0:
                thread_data = self.get_thread_replies(channel, msg["ts"])
                if "messages" in thread_data:
                    enriched_msg["thread_replies"] = [
                        {"text": r.get("text", ""), "user": r.get("user")}
                        for r in thread_data["messages"][1:]  # Skip parent
                    ]

            enriched.append(enriched_msg)

        return {
            "channel": channel,
            "count": len(enriched),
            "messages": enriched,
            "note": (
                "Use your intelligence to analyze this data. "
                "Look for patterns, unanswered questions, "
                "engagement levels, sentiment and anything user asks for."
            ),
        }

    # ============================================================
    # Phase 2: Workflow Automation
    # ============================================================

    def trigger_workflow(
        self,
        webhook_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a Slack Workflow via webhook.

        Args:
            webhook_url: The workflow's webhook URL
            payload: Optional JSON payload to send
        """
        body = payload or {}

        response = httpx.post(
            webhook_url,
            json=body,
            timeout=30.0,
        )

        if response.status_code != 200:
            return {"error": f"Workflow trigger failed: {response.status_code}"}

        return {"success": True, "status_code": response.status_code}

    # ============================================================
    # Phase 3: Critical Power Tools
    # ============================================================

    def get_conversation_context(
        self,
        channel: str,
        limit: int = 20,
        include_user_info: bool = True,
    ) -> dict[str, Any]:
        """Get rich conversation context for AI understanding.

        Fetches recent messages with user details, making it easy for
        the agent to understand who said what and respond appropriately.

        Args:
            channel: Channel ID
            limit: Number of messages to fetch
            include_user_info: Whether to resolve user IDs to names
        """
        history = self.get_history(channel, limit=limit)
        if "error" in history:
            return history

        messages = history.get("messages", [])

        # Build user cache to avoid repeated lookups
        user_cache: dict[str, str] = {}

        context_messages = []
        for msg in messages:
            user_id = msg.get("user", "unknown")

            # Resolve user name if requested
            user_name = user_id
            if include_user_info and user_id != "unknown":
                if user_id not in user_cache:
                    user_info = self.get_user_info(user_id)
                    if "user" in user_info:
                        user_cache[user_id] = user_info["user"].get("real_name", user_id)
                    else:
                        user_cache[user_id] = user_id
                user_name = user_cache[user_id]

            context_messages.append(
                {
                    "user_id": user_id,
                    "user_name": user_name,
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts"),
                    "has_replies": msg.get("reply_count", 0) > 0,
                }
            )

        return {
            "channel": channel,
            "message_count": len(context_messages),
            "messages": context_messages,
            "users_in_conversation": list(user_cache.values()),
        }

    def find_user_by_email(
        self,
        email: str,
    ) -> dict[str, Any]:
        """Find a Slack user by their email address.

        CRITICAL for CRM integrations - bridges email addresses
        to Slack user IDs for DMs and mentions.

        Args:
            email: User's email address
        """
        response = httpx.get(
            f"{SLACK_API_BASE}/users.lookupByEmail",
            headers=self._headers,
            params={"email": email},
            timeout=30.0,
        )
        return self._handle_response(response)

    def kick_user_from_channel(
        self,
        channel: str,
        user: str,
    ) -> dict[str, Any]:
        """Remove a user from a channel.

        Args:
            channel: Channel ID
            user: User ID to remove
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/conversations.kick",
            headers=self._headers,
            json={"channel": channel, "user": user},
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_file(
        self,
        file_id: str,
    ) -> dict[str, Any]:
        """Delete a file from Slack.

        Args:
            file_id: The file ID to delete
        """
        response = httpx.post(
            f"{SLACK_API_BASE}/files.delete",
            headers=self._headers,
            json={"file": file_id},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_team_stats(self) -> dict[str, Any]:
        """Get high-level workspace statistics.

        Provides an overview of the team including user count
        and basic team info.
        """
        # Get team info
        team_response = httpx.get(
            f"{SLACK_API_BASE}/team.info",
            headers=self._headers,
            timeout=30.0,
        )
        team_data = self._handle_response(team_response)

        # Get user count
        users_response = httpx.get(
            f"{SLACK_API_BASE}/users.list",
            headers=self._headers,
            params={"limit": 1},  # Just need cursor metadata
            timeout=30.0,
        )
        users_data = self._handle_response(users_response)

        if "error" in team_data:
            return team_data

        team = team_data.get("team", {})
        members = users_data.get("members", [])

        return {
            "team_name": team.get("name"),
            "team_domain": team.get("domain"),
            "team_id": team.get("id"),
            "member_count_sample": len(members),
            "note": "For exact member count, paginate through users.list",
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Slack tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get Slack bot token from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("slack", account)
            token = credentials.get("slack")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('slack'), got {type(token).__name__}"
                )
            return token
        return os.getenv("SLACK_BOT_TOKEN")

    def _get_user_token() -> str | None:
        """Get Slack user token for search API."""
        if credentials is not None:
            return credentials.get("slack_user")
        return os.getenv("SLACK_USER_TOKEN")

    def _get_client(account: str = "") -> _SlackClient | dict[str, str]:
        """Get a Slack client, or return an error dict if no credentials."""
        token = _get_token(account)
        if not token:
            return {
                "error": "Slack credentials not configured",
                "help": (
                    "Set SLACK_BOT_TOKEN environment variable or configure via credential store"
                ),
            }
        user_token = _get_user_token()
        return _SlackClient(token, user_token=user_token)

    # --- Messages ---

    @mcp.tool()
    def slack_send_message(
        channel: str,
        text: str,
        thread_ts: str | None = None,
        account: str = "",
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
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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
        account: str = "",
    ) -> dict:
        """
        Get recent messages from a Slack channel.

        Args:
            channel: Channel ID (e.g., 'C0123456789')
            limit: Maximum number of messages to return (1-1000, default 20)

        Returns:
            Dict with list of messages or error
        """
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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
    def slack_get_user_info(user_id: str, account: str = "") -> dict:
        """
        Get information about a Slack user.

        Args:
            user_id: User ID (e.g., 'U0123456789')

        Returns:
            Dict with user profile information or error
        """
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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
    def slack_delete_message(channel: str, ts: str, account: str = "") -> dict:
        """
        Delete a Slack message.

        Args:
            channel: Channel ID where the message is
            ts: Message timestamp (ts) to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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
        account: str = "",
    ) -> dict:
        """
        Create a new Slack channel.

        Args:
            name: Channel name (lowercase, no spaces, use hyphens)
            is_private: If True, create a private channel

        Returns:
            Dict with new channel details or error
        """
        client = _get_client(account)
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
    def slack_archive_channel(channel: str, account: str = "") -> dict:
        """
        Archive a Slack channel.

        Args:
            channel: Channel ID to archive

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
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
    def slack_invite_to_channel(channel: str, user_ids: str, account: str = "") -> dict:
        """
        Invite users to a Slack channel.

        Args:
            channel: Channel ID
            user_ids: Comma-separated user IDs (e.g., 'U001,U002')

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
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
    def slack_set_channel_topic(channel: str, topic: str, account: str = "") -> dict:
        """
        Set the topic for a Slack channel.

        Args:
            channel: Channel ID
            topic: New topic text

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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
    def slack_list_users(limit: int = 100, account: str = "") -> dict:
        """
        List users in the Slack workspace.

        Args:
            limit: Maximum number of users to return (1-1000, default 100)

        Returns:
            Dict with list of users or error
        """
        client = _get_client(account)
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
        account: str = "",
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
        client = _get_client(account)
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

    # --- Search ---

    @mcp.tool()
    def slack_search_messages(
        query: str,
        count: int = 20,
        account: str = "",
    ) -> dict:
        """
        Search for messages across the Slack workspace.

        Args:
            query: Search query (supports Slack search modifiers like from:, in:, has:)
            count: Maximum results to return (1-100, default 20)

        Returns:
            Dict with matching messages or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.search_messages(query, count)
            if "error" in result:
                return result
            messages = result.get("messages", {})
            matches = messages.get("matches", [])
            return {
                "success": True,
                "total": messages.get("total", 0),
                "messages": [
                    {
                        "text": m.get("text"),
                        "user": m.get("user"),
                        "channel": m.get("channel", {}).get("name"),
                        "ts": m.get("ts"),
                        "permalink": m.get("permalink"),
                    }
                    for m in matches
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Threads ---

    @mcp.tool()
    def slack_get_thread_replies(
        channel: str,
        thread_ts: str,
        limit: int = 50,
        account: str = "",
    ) -> dict:
        """
        Get all replies in a message thread.

        Args:
            channel: Channel ID where the thread is
            thread_ts: Timestamp of the parent message
            limit: Maximum replies to return (default 50)

        Returns:
            Dict with thread messages or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_thread_replies(channel, thread_ts, limit)
            if "error" in result:
                return result
            messages = [
                {
                    "ts": m.get("ts"),
                    "user": m.get("user"),
                    "text": m.get("text"),
                }
                for m in result.get("messages", [])
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

    # --- Pins ---

    @mcp.tool()
    def slack_pin_message(channel: str, timestamp: str, account: str = "") -> dict:
        """
        Pin a message to a channel.

        Args:
            channel: Channel ID
            timestamp: Message timestamp (ts) to pin

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.pin_message(channel, timestamp)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_unpin_message(channel: str, timestamp: str, account: str = "") -> dict:
        """
        Unpin a message from a channel.

        Args:
            channel: Channel ID
            timestamp: Message timestamp (ts) to unpin

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.unpin_message(channel, timestamp)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_list_pins(channel: str, account: str = "") -> dict:
        """
        List all pinned items in a channel.

        Args:
            channel: Channel ID

        Returns:
            Dict with pinned items or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_pins(channel)
            if "error" in result:
                return result
            items = result.get("items", [])
            return {
                "success": True,
                "pins": [
                    {
                        "type": item.get("type"),
                        "created": item.get("created"),
                        "message": item.get("message", {}).get("text"),
                    }
                    for item in items
                ],
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Bookmarks ---

    @mcp.tool()
    def slack_add_bookmark(
        channel: str,
        title: str,
        link: str,
        emoji: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Add a bookmark/link to a channel.

        Args:
            channel: Channel ID
            title: Bookmark title
            link: URL to bookmark
            emoji: Optional emoji for the bookmark

        Returns:
            Dict with bookmark details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.add_bookmark(channel, title, link, emoji)
            if "error" in result:
                return result
            bookmark = result.get("bookmark", {})
            return {
                "success": True,
                "bookmark": {
                    "id": bookmark.get("id"),
                    "title": bookmark.get("title"),
                    "link": bookmark.get("link"),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Scheduled Messages Management ---

    @mcp.tool()
    def slack_list_scheduled_messages(channel: str | None = None, account: str = "") -> dict:
        """
        List all scheduled messages.

        Args:
            channel: Optional channel ID to filter by

        Returns:
            Dict with scheduled messages or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_scheduled_messages(channel)
            if "error" in result:
                return result
            messages = result.get("scheduled_messages", [])
            return {
                "success": True,
                "scheduled_messages": [
                    {
                        "id": m.get("id"),
                        "channel_id": m.get("channel_id"),
                        "post_at": m.get("post_at"),
                        "text": m.get("text"),
                    }
                    for m in messages
                ],
                "count": len(messages),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_delete_scheduled_message(
        channel: str,
        scheduled_message_id: str,
        account: str = "",
    ) -> dict:
        """
        Delete/cancel a scheduled message.

        Args:
            channel: Channel ID where message was scheduled
            scheduled_message_id: ID of the scheduled message

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_scheduled_message(channel, scheduled_message_id)
            if "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Direct Messages ---

    @mcp.tool()
    def slack_send_dm(user_id: str, text: str, account: str = "") -> dict:
        """
        Send a direct message to a user.

        Args:
            user_id: User ID to send DM to
            text: Message text

        Returns:
            Dict with message details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            # First open/get DM channel
            dm_result = client.open_dm(user_id)
            if "error" in dm_result:
                return dm_result
            channel_id = dm_result.get("channel", {}).get("id")
            if not channel_id:
                return {"error": "Failed to open DM channel"}

            # Now send message
            result = client.post_message(channel_id, text)
            if "error" in result:
                return result
            return {
                "success": True,
                "channel": channel_id,
                "ts": result.get("ts"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Message Utilities ---

    @mcp.tool()
    def slack_get_permalink(channel: str, message_ts: str, account: str = "") -> dict:
        """
        Get a permanent link to a message.

        Args:
            channel: Channel ID
            message_ts: Message timestamp

        Returns:
            Dict with permalink or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_permalink(channel, message_ts)
            if "error" in result:
                return result
            return {
                "success": True,
                "permalink": result.get("permalink"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_send_ephemeral(
        channel: str,
        user_id: str,
        text: str,
        account: str = "",
    ) -> dict:
        """
        Send an ephemeral message visible only to one user.

        Args:
            channel: Channel ID
            user_id: User ID who will see the message
            text: Message text

        Returns:
            Dict with message timestamp or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.post_ephemeral(channel, user_id, text)
            if "error" in result:
                return result
            return {
                "success": True,
                "message_ts": result.get("message_ts"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # ==========================================================================
    # Advanced Features: Block Kit & Views
    # ==========================================================================

    @mcp.tool()
    def slack_post_blocks(
        channel: str,
        blocks: str,
        text: str = "Message with blocks",
        thread_ts: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Send a rich Block Kit message to a channel.

        Args:
            channel: Channel ID
            blocks: JSON string of Block Kit blocks (will be parsed)
            text: Fallback text for notifications
            thread_ts: Optional thread timestamp

        Returns:
            Dict with message details or error

        Example blocks (JSON string):
            '[{"type": "section", "text": {"type": "mrkdwn", "text": "*Hello* world"}}]'
        """
        import json as json_module

        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            # Parse blocks JSON
            try:
                blocks_list = json_module.loads(blocks)
            except json_module.JSONDecodeError as e:
                return {"error": f"Invalid blocks JSON: {e}"}

            result = client.post_message(channel, text, thread_ts, blocks=blocks_list)
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
    def slack_open_modal(
        trigger_id: str,
        title: str,
        blocks: str,
        submit_label: str = "Submit",
        close_label: str = "Cancel",
        callback_id: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Open a modal dialog. Requires a trigger_id from a slash command or button click.

        Args:
            trigger_id: From interaction payload (expires in 3 seconds)
            title: Modal title (max 24 chars)
            blocks: JSON string of Block Kit blocks for modal body
            submit_label: Text for submit button
            close_label: Text for close button
            callback_id: Optional identifier for the modal

        Returns:
            Dict with view ID or error
        """
        import json as json_module

        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            try:
                blocks_list = json_module.loads(blocks)
            except json_module.JSONDecodeError as e:
                return {"error": f"Invalid blocks JSON: {e}"}

            view = {
                "type": "modal",
                "title": {"type": "plain_text", "text": title[:24]},
                "submit": {"type": "plain_text", "text": submit_label},
                "close": {"type": "plain_text", "text": close_label},
                "blocks": blocks_list,
            }
            if callback_id:
                view["callback_id"] = callback_id

            result = client.open_modal(trigger_id, view)
            if "error" in result:
                return result
            return {
                "success": True,
                "view_id": result.get("view", {}).get("id"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_update_home_tab(
        user_id: str,
        blocks: str,
        account: str = "",
    ) -> dict:
        """
        Publish/update a user's App Home tab.

        Args:
            user_id: User ID to update home tab for
            blocks: JSON string of Block Kit blocks for home tab

        Returns:
            Dict with success status or error
        """
        import json as json_module

        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            try:
                blocks_list = json_module.loads(blocks)
            except json_module.JSONDecodeError as e:
                return {"error": f"Invalid blocks JSON: {e}"}

            view = {
                "type": "home",
                "blocks": blocks_list,
            }

            result = client.publish_home_tab(user_id, view)
            if "error" in result:
                return result
            return {
                "success": True,
                "view_id": result.get("view", {}).get("id"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: User Status & Presence
    # =========================================================================

    @mcp.tool()
    def slack_set_status(
        status_text: str,
        status_emoji: str | None = None,
        expiration_minutes: int | None = None,
        account: str = "",
    ) -> dict:
        """
        Set the authenticated user's status message and emoji.

        Args:
            status_text: Status message (e.g., 'In a meeting')
            status_emoji: Optional emoji (e.g., ':calendar:')
            expiration_minutes: Minutes until status clears (0 = never)

        Returns:
            Dict with updated profile or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            import time

            expiration = None
            if expiration_minutes is not None and expiration_minutes > 0:
                expiration = int(time.time()) + (expiration_minutes * 60)

            result = client.set_user_status(status_text, status_emoji, expiration)
            if "error" in result:
                return result
            return {
                "success": True,
                "status_text": status_text,
                "status_emoji": status_emoji,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_set_presence(presence: str, account: str = "") -> dict:
        """
        Set the bot's presence status.

        Args:
            presence: 'auto' (online when active) or 'away' (always show away)

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        if presence not in ("auto", "away"):
            return {"error": "presence must be 'auto' or 'away'"}
        try:
            result = client.set_presence(presence)
            if "error" in result:
                return result
            return {"success": True, "presence": presence}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_get_presence(user_id: str, account: str = "") -> dict:
        """
        Get a user's current presence status.

        Args:
            user_id: Slack user ID (e.g., 'U0123456789')

        Returns:
            Dict with presence info (active, away) or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_presence(user_id)
            if "error" in result:
                return result
            return {
                "user_id": user_id,
                "presence": result.get("presence"),
                "online": result.get("online", False),
                "auto_away": result.get("auto_away", False),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: Reminders
    # =========================================================================

    @mcp.tool()
    def slack_create_reminder(
        text: str,
        time: str,
        user_id: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Create a reminder for yourself or another user.

        Args:
            text: Reminder message
            time: When to remind (e.g., 'in 5 minutes', 'tomorrow at 9am', or Unix timestamp)
            user_id: Optional user ID to remind (defaults to yourself)

        Returns:
            Dict with reminder details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_reminder(text, time, user_id)
            if "error" in result:
                return result
            reminder = result.get("reminder", {})
            return {
                "success": True,
                "reminder_id": reminder.get("id"),
                "text": reminder.get("text"),
                "time": reminder.get("time"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_list_reminders(account: str = "") -> dict:
        """
        List all pending reminders for the authenticated user.

        Returns:
            Dict with list of reminders or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_reminders()
            if "error" in result:
                return result
            reminders = result.get("reminders", [])
            return {
                "count": len(reminders),
                "reminders": [
                    {
                        "id": r.get("id"),
                        "text": r.get("text"),
                        "time": r.get("time"),
                        "complete_ts": r.get("complete_ts"),
                    }
                    for r in reminders
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_delete_reminder(reminder_id: str, account: str = "") -> dict:
        """
        Delete/cancel a reminder.

        Args:
            reminder_id: The ID of the reminder to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_reminder(reminder_id)
            if "error" in result:
                return result
            return {"success": True, "deleted": reminder_id}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: User Groups
    # =========================================================================

    @mcp.tool()
    def slack_create_usergroup(
        name: str,
        handle: str | None = None,
        description: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Create a user group for @mentions.

        Args:
            name: Display name for the group
            handle: Short name for @mentioning (e.g., 'design-team')
            description: Optional description

        Returns:
            Dict with usergroup details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_usergroup(name, handle, description)
            if "error" in result:
                return result
            ug = result.get("usergroup", {})
            return {
                "success": True,
                "usergroup_id": ug.get("id"),
                "name": ug.get("name"),
                "handle": ug.get("handle"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_update_usergroup_members(
        usergroup_id: str,
        user_ids: str,
        account: str = "",
    ) -> dict:
        """
        Set the members of a user group.

        Args:
            usergroup_id: The user group ID
            user_ids: Comma-separated list of user IDs to set as members

        Returns:
            Dict with updated usergroup or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            users = [u.strip() for u in user_ids.split(",") if u.strip()]
            result = client.update_usergroup_members(usergroup_id, users)
            if "error" in result:
                return result
            return {
                "success": True,
                "usergroup_id": usergroup_id,
                "members_count": len(users),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_list_usergroups(account: str = "") -> dict:
        """
        List all user groups in the workspace.

        Returns:
            Dict with list of usergroups or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_usergroups()
            if "error" in result:
                return result
            groups = result.get("usergroups", [])
            return {
                "count": len(groups),
                "usergroups": [
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "handle": g.get("handle"),
                        "user_count": g.get("user_count", 0),
                    }
                    for g in groups
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: Emoji
    # =========================================================================

    @mcp.tool()
    def slack_list_emoji(account: str = "") -> dict:
        """
        List all custom emoji in the workspace.

        Returns:
            Dict with emoji names and URLs or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_emoji()
            if "error" in result:
                return result
            emoji = result.get("emoji", {})
            return {
                "count": len(emoji),
                "emoji": list(emoji.keys())[:100],  # Limit to first 100
                "sample": dict(list(emoji.items())[:10]),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: Canvas
    # =========================================================================

    @mcp.tool()
    def slack_create_canvas(
        title: str,
        markdown_content: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Create a new Slack Canvas (collaborative document).

        Args:
            title: Canvas title
            markdown_content: Optional initial markdown content

        Returns:
            Dict with canvas ID or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            doc_content = None
            if markdown_content:
                doc_content = {
                    "type": "markdown",
                    "markdown": markdown_content,
                }

            result = client.create_canvas(title, doc_content)
            if "error" in result:
                return result
            return {
                "success": True,
                "canvas_id": result.get("canvas_id"),
                "title": title,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_edit_canvas(
        canvas_id: str,
        markdown_content: str,
        operation: str = "insert_at_end",
        account: str = "",
    ) -> dict:
        """
        Edit a Slack Canvas document.

        Args:
            canvas_id: The canvas document ID
            markdown_content: Markdown content to add
            operation: 'insert_at_start', 'insert_at_end', or 'replace'

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            changes = [
                {
                    "operation": operation,
                    "document_content": {
                        "type": "markdown",
                        "markdown": markdown_content,
                    },
                }
            ]

            result = client.edit_canvas(canvas_id, changes)
            if "error" in result:
                return result
            return {
                "success": True,
                "canvas_id": canvas_id,
                "operation": operation,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: Analytics (AI-Driven Data Fetcher)
    # =========================================================================
    #
    # DESIGN: This tool returns RAW message data. The AI agent uses its
    # intelligence to analyze, find patterns, identify unanswered questions,
    # compute engagement, detect sentiment, etc. No rule-based logic.
    # =========================================================================

    @mcp.tool()
    def slack_get_messages_for_analysis(
        channel: str,
        limit: int = 100,
        include_threads: bool = True,
        account: str = "",
    ) -> dict:
        """
        Fetch rich message data from a channel for AI-powered analysis.

        This tool returns raw, structured message data. As an AI agent,
        YOU should use your intelligence to analyze this data for:
        - Finding unanswered questions (look for messages with no replies
          that seem to be asking something)
        - Engagement analysis (look at reactions, thread activity, patterns)
        - Activity reports (analyze timestamps, posting frequency, etc.)
        - Sentiment analysis (understand the tone of messages)
        - Key topics and trends

        Args:
            channel: Channel ID to fetch messages from
            limit: Number of messages to fetch (max 100)
            include_threads: Whether to include thread replies for context

        Returns:
            Dict with messages including text, user, reactions, thread info
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_messages_for_analysis(channel, limit, include_threads)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 2 Tools: Workflow Automation
    # =========================================================================

    @mcp.tool()
    def slack_trigger_workflow(
        webhook_url: str,
        payload: str | None = None,
        account: str = "",
    ) -> dict:
        """
        Trigger a Slack Workflow via its webhook URL.

        Args:
            webhook_url: The workflow's webhook URL (from Workflow Builder)
            payload: Optional JSON string payload to send

        Returns:
            Dict with success status or error
        """
        import json as json_module

        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            payload_dict = None
            if payload:
                try:
                    payload_dict = json_module.loads(payload)
                except json_module.JSONDecodeError as e:
                    return {"error": f"Invalid payload JSON: {e}"}

            return client.trigger_workflow(webhook_url, payload_dict)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # =========================================================================
    # Phase 3 Tools: Critical Power Tools
    # =========================================================================

    @mcp.tool()
    def slack_get_conversation_context(
        channel: str,
        limit: int = 20,
        include_user_info: bool = True,
        account: str = "",
    ) -> dict:
        """
        Get rich conversation context with user names resolved.

        Perfect for understanding who said what before responding.
        Returns messages with real names instead of just user IDs.

        Args:
            channel: Channel ID
            limit: Number of messages to fetch (default 20)
            include_user_info: Resolve user IDs to names (default True)

        Returns:
            Dict with messages including user names and conversation summary
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_conversation_context(channel, limit, include_user_info)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_find_user_by_email(
        email: str,
        account: str = "",
    ) -> dict:
        """
        Find a Slack user by their email address.

        CRITICAL for CRM integrations - bridges email addresses to Slack
        user IDs so you can DM or mention them.

        Args:
            email: User's email address

        Returns:
            Dict with user info including ID, name, etc.
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.find_user_by_email(email)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_kick_user_from_channel(
        channel: str,
        user: str,
        account: str = "",
    ) -> dict:
        """
        Remove a user from a channel.

        Admin tool for moderation and access control.

        Args:
            channel: Channel ID
            user: User ID to remove

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.kick_user_from_channel(channel, user)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_delete_file(
        file_id: str,
        account: str = "",
    ) -> dict:
        """
        Delete a file from Slack.

        Useful for cleaning up temporary reports or CSVs after processing.

        Args:
            file_id: The file ID to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.delete_file(file_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def slack_get_team_stats(account: str = "") -> dict:
        """
        Get high-level workspace statistics.

        Provides overview of the team including name, domain, and member count.

        Returns:
            Dict with team info and member statistics
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_team_stats()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
