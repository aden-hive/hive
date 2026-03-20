#!/usr/bin/env python3
"""
Slack MCP Server for Meeting Notes Agent
=========================================
A Model Context Protocol (MCP) server that provides Slack integration tools.

Usage:
    python slack_mcp_server.py

Environment Variables:
    SLACK_BOT_TOKEN - Slack Bot OAuth token (xoxb-...)
"""

import json
import logging
import os
import sys
from typing import Any

import httpx
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("slack-mcp-server")

SLACK_API_BASE = "https://slack.com/api"

# Create FastMCP server instance
mcp = FastMCP("slack-tools")


def get_slack_token() -> str:
    """Get Slack bot token from environment."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "SLACK_BOT_TOKEN environment variable is required. "
            "Set it in your .env file or environment."
        )
    return token


async def slack_api_call(endpoint: str, payload: dict) -> dict:
    """Make an async POST request to the Slack Web API."""
    token = get_slack_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"{SLACK_API_BASE}/{endpoint}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(f"Slack API HTTP error {exc.response.status_code}: {exc.response.text}")
            return {"ok": False, "error": f"HTTP {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.error(f"Slack API request error: {exc}")
            return {"ok": False, "error": str(exc)}


@mcp.tool()
async def slack_post_message(
    channel: str,
    text: str,
    blocks: list[dict] | None = None,
    username: str | None = None,
    icon_emoji: str | None = None,
) -> str:
    """
    Post a message to a Slack channel with optional Block Kit formatting.
    
    Args:
        channel: Slack channel ID (C012AB3CD) or name (#general)
        text: Plain text message content (fallback for notifications)
        blocks: Optional Slack Block Kit blocks for rich formatting
        username: Override bot display name
        icon_emoji: Override bot icon emoji (e.g., ':bee:')
    
    Returns:
        JSON string with result including ok status and message timestamp
    """
    payload: dict[str, Any] = {
        "channel": channel,
        "text": text,
    }
    
    if blocks:
        payload["blocks"] = blocks
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    
    logger.info(f"Posting message to Slack channel: {channel}")
    result = await slack_api_call("chat.postMessage", payload)
    
    if result.get("ok"):
        logger.info(f"Message posted successfully. ts={result.get('ts')}")
    else:
        logger.warning(f"Failed to post message: {result.get('error')}")
    
    return json.dumps(result, indent=2)


@mcp.tool()
async def slack_list_channels(
    limit: int = 100,
    cursor: str | None = None,
) -> str:
    """
    List public Slack channels the bot has access to.
    
    Args:
        limit: Maximum number of channels to return (1-1000)
        cursor: Pagination cursor from previous response
    
    Returns:
        JSON string with channels list and next_cursor for pagination
    """
    payload: dict[str, Any] = {
        "limit": limit,
        "exclude_archived": True,
    }
    
    if cursor:
        payload["cursor"] = cursor
    
    logger.info("Listing Slack channels")
    result = await slack_api_call("conversations.list", payload)
    
    # Simplify response for readability
    if result.get("ok"):
        channels = result.get("channels", [])
        simplified = {
            "ok": True,
            "count": len(channels),
            "channels": [
                {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_member": ch.get("is_member", False),
                }
                for ch in channels
            ],
            "next_cursor": result.get("response_metadata", {}).get("next_cursor", ""),
        }
        return json.dumps(simplified, indent=2)
    else:
        return json.dumps(result, indent=2)


if __name__ == "__main__":
    # Verify token is available at startup
    try:
        token = get_slack_token()
        logger.info(f"Slack token found: {token[:10]}...")
    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)
    
    # Run the MCP server
    mcp.run()

