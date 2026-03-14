"""
Slack Tool — MCP Integration for Aden Hive
==========================================
Provides tools for posting messages to Slack channels using the
Slack Web API. Follows the aden_tools MCP tool pattern.

Credentials required (via hive credential store or env vars):
    SLACK_BOT_TOKEN — Slack Bot OAuth token (xoxb-...)

Scopes required on the Slack app:
    - chat:write
    - chat:write.public   (to post to channels the bot hasn't joined)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


# ─────────────────────────────────────────────────────────────────────────────
# Credential Spec (used by hive credential store)
# ─────────────────────────────────────────────────────────────────────────────

CREDENTIAL_SPEC = {
    "id": "slack",
    "name": "Slack",
    "description": "Slack Bot OAuth token for posting messages",
    "fields": [
        {
            "key": "SLACK_BOT_TOKEN",
            "label": "Bot Token",
            "description": "Your Slack Bot OAuth token starting with xoxb-",
            "secret": True,
            "required": True,
        }
    ],
    "setup_url": "https://api.slack.com/apps",
    "docs_url": "https://api.slack.com/authentication/token-types#bot",
}


# ─────────────────────────────────────────────────────────────────────────────
# Input / Output Schemas
# ─────────────────────────────────────────────────────────────────────────────

class SlackPostMessageInput(BaseModel):
    channel: str = Field(..., description="Slack channel ID or name (e.g. C012AB3CD or #general)")
    text: str = Field(..., description="Fallback plain-text message (shown in notifications)")
    blocks: list[dict] | None = Field(
        default=None, description="Optional Slack Block Kit blocks array"
    )
    username: str | None = Field(default=None, description="Bot display name override")
    icon_emoji: str | None = Field(default=None, description="Bot icon emoji override (e.g. :bee:)")
    thread_ts: str | None = Field(
        default=None, description="Thread timestamp to reply into a thread"
    )


class SlackPostMessageOutput(BaseModel):
    ok: bool
    channel: str | None = None
    ts: str | None = None
    message: dict | None = None
    error: str | None = None


class SlackGetChannelsInput(BaseModel):
    limit: int = Field(default=100, description="Max channels to return", ge=1, le=1000)
    cursor: str | None = Field(default=None, description="Pagination cursor")


# ─────────────────────────────────────────────────────────────────────────────
# Core Functions
# ─────────────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "SLACK_BOT_TOKEN environment variable is not set. "
            "Run: hive credentials set slack SLACK_BOT_TOKEN <your-token>"
        )
    return token


def _slack_request(endpoint: str, payload: dict) -> dict:
    """Make a POST request to the Slack Web API."""
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"{SLACK_API_BASE}/{endpoint}"
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Slack API HTTP error %s: %s", exc.response.status_code, exc.response.text)
        raise
    except httpx.RequestError as exc:
        logger.error("Slack API request error: %s", exc)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool: slack_post_message
# ─────────────────────────────────────────────────────────────────────────────

def slack_post_message(
    channel: str,
    text: str,
    blocks: list[dict] | None = None,
    username: str | None = None,
    icon_emoji: str | None = None,
    thread_ts: str | None = None,
) -> SlackPostMessageOutput:
    """
    Post a message to a Slack channel.

    Args:
        channel: Channel ID (C012AB3CD) or name (#general)
        text: Fallback plain-text content (required by Slack even when blocks are used)
        blocks: Optional Block Kit blocks for rich formatting
        username: Display name override for the bot
        icon_emoji: Emoji for the bot avatar (e.g. ':bee:')
        thread_ts: Timestamp to reply in a thread

    Returns:
        SlackPostMessageOutput with ok status and message timestamp
    """
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    if thread_ts:
        payload["thread_ts"] = thread_ts

    logger.info("Posting Slack message to channel=%s", channel)
    result = _slack_request("chat.postMessage", payload)

    output = SlackPostMessageOutput(
        ok=result.get("ok", False),
        channel=result.get("channel"),
        ts=result.get("ts"),
        message=result.get("message"),
        error=result.get("error"),
    )

    if not output.ok:
        logger.warning("Slack post failed: %s", output.error)
    else:
        logger.info("Slack message sent. ts=%s", output.ts)

    return output


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool: slack_list_channels
# ─────────────────────────────────────────────────────────────────────────────

def slack_list_channels(limit: int = 100, cursor: str | None = None) -> dict:
    """
    List public Slack channels the bot has access to.

    Args:
        limit: Maximum number of channels to return (1-1000)
        cursor: Pagination cursor from a previous response

    Returns:
        Dict with channels list and next_cursor for pagination
    """
    payload: dict[str, Any] = {"limit": limit, "exclude_archived": True}
    if cursor:
        payload["cursor"] = cursor

    result = _slack_request("conversations.list", payload)
    return {
        "ok": result.get("ok", False),
        "channels": result.get("channels", []),
        "next_cursor": result.get("response_metadata", {}).get("next_cursor", ""),
        "error": result.get("error"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool: slack_post_meeting_notes (convenience wrapper)
# ─────────────────────────────────────────────────────────────────────────────

def slack_post_meeting_notes(
    channel: str,
    meeting_notes: dict,
    meeting_name: str = "Meeting Notes",
    meeting_date: str = "",
) -> SlackPostMessageOutput:
    """
    High-level convenience tool: formats and posts meeting notes to Slack.
    Accepts a MeetingNotesOutput-shaped dict and handles Block Kit formatting.

    Args:
        channel: Target Slack channel
        meeting_notes: Dict matching MeetingNotesOutput schema
        meeting_name: Meeting title
        meeting_date: Meeting date string

    Returns:
        SlackPostMessageOutput
    """
    # Import here to avoid circular import in standalone tool usage
    from meeting_notes_agent.agent import MeetingNotesOutput, _build_slack_blocks  # noqa

    notes = MeetingNotesOutput(**meeting_notes)
    blocks = _build_slack_blocks(notes, meeting_name, meeting_date)

    return slack_post_message(
        channel=channel,
        text=f"🐝 {meeting_name} — Meeting Notes",
        blocks=blocks,
        icon_emoji=":bee:",
        username="Hive Meeting Agent",
    )


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool Registration (used by aden_tools mcp_server.py pattern)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "slack_post_message": {
        "function": slack_post_message,
        "description": "Post a message to a Slack channel with optional Block Kit blocks",
        "credential_spec": CREDENTIAL_SPEC,
        "input_schema": SlackPostMessageInput.model_json_schema(),
    },
    "slack_list_channels": {
        "function": slack_list_channels,
        "description": "List Slack channels the bot has access to",
        "credential_spec": CREDENTIAL_SPEC,
        "input_schema": SlackGetChannelsInput.model_json_schema(),
    },
    "slack_post_meeting_notes": {
        "function": slack_post_meeting_notes,
        "description": "Format and post meeting notes directly to a Slack channel",
        "credential_spec": CREDENTIAL_SPEC,
    },
}