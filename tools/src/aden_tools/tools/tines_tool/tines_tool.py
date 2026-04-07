"""Tines API integration.

Provides security automation workflow management via the Tines REST API.
Requires TINES_DOMAIN and TINES_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _get_config() -> tuple[str, dict] | dict:
    """Return (base_url, headers) or error dict."""
    domain = os.getenv("TINES_DOMAIN", "").rstrip("/")
    api_key = os.getenv("TINES_API_KEY", "")
    if not domain or not api_key:
        return {
            "error": "TINES_DOMAIN and TINES_API_KEY are required",
            "help": "Set TINES_DOMAIN and TINES_API_KEY environment variables",
        }
    base_url = f"https://{domain}/api/v1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    return base_url, headers


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Tines tools."""

    @mcp.tool()
    def tines_list_stories(
        team_id: int = 0,
        search: str = "",
        per_page: int = 20,
    ) -> dict:
        """List Tines stories (workflows).

        Args:
            team_id: Filter by team ID (0 for all).
            search: Search stories by name.
            per_page: Results per page (max 500, default 20).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {"per_page": min(per_page, 500)}
        if team_id > 0:
            params["team_id"] = team_id
        if search:
            params["search"] = search

        data = _get(f"{base_url}/stories", headers, params)
        if "error" in data:
            return data

        stories = data.get("stories", [])
        return {
            "count": len(stories),
            "stories": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "disabled": s.get("disabled"),
                    "mode": s.get("mode"),
                    "team_id": s.get("team_id"),
                    "tags": s.get("tags", []),
                    "created_at": s.get("created_at"),
                    "updated_at": s.get("updated_at"),
                }
                for s in stories
            ],
        }

    @mcp.tool()
    def tines_get_story(story_id: int) -> dict:
        """Get details of a specific Tines story.

        Args:
            story_id: The story ID.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if story_id <= 0:
            return {"error": "story_id is required"}

        data = _get(f"{base_url}/stories/{story_id}", headers)
        if "error" in data:
            return data

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": data.get("description"),
            "disabled": data.get("disabled"),
            "mode": data.get("mode"),
            "team_id": data.get("team_id"),
            "folder_id": data.get("folder_id"),
            "tags": data.get("tags", []),
            "send_to_story_enabled": data.get("send_to_story_enabled"),
            "entry_agent_id": data.get("entry_agent_id"),
            "exit_agents": data.get("exit_agents", []),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @mcp.tool()
    def tines_list_actions(
        story_id: int = 0,
        action_type: str = "",
        per_page: int = 20,
    ) -> dict:
        """List Tines actions (agents) in stories.

        Args:
            story_id: Filter by story ID (0 for all).
            action_type: Filter by action type (e.g. 'HTTPRequestAgent', 'WebhookAgent').
            per_page: Results per page (max 500, default 20).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {"per_page": min(per_page, 500)}
        if story_id > 0:
            params["story_id"] = story_id
        if action_type:
            params["action_type"] = action_type

        data = _get(f"{base_url}/actions", headers, params)
        if "error" in data:
            return data

        agents = data.get("agents", [])
        return {
            "count": len(agents),
            "actions": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "type": a.get("type"),
                    "story_id": a.get("story_id"),
                    "disabled": a.get("disabled"),
                    "created_at": a.get("created_at"),
                    "updated_at": a.get("updated_at"),
                }
                for a in agents
            ],
        }

    @mcp.tool()
    def tines_get_action(action_id: int) -> dict:
        """Get details of a specific Tines action (agent).

        Args:
            action_id: The action ID.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if action_id <= 0:
            return {"error": "action_id is required"}

        data = _get(f"{base_url}/actions/{action_id}", headers)
        if "error" in data:
            return data

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "description": data.get("description"),
            "story_id": data.get("story_id"),
            "disabled": data.get("disabled"),
            "sources": data.get("sources", []),
            "receivers": data.get("receivers", []),
            "options": data.get("options", {}),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @mcp.tool()
    def tines_get_action_logs(
        action_id: int,
        level: int = 0,
        per_page: int = 20,
    ) -> dict:
        """Get logs for a Tines action.

        Args:
            action_id: The action ID.
            level: Filter by log level: 2=warning, 3=info, 4=error (0 for all).
            per_page: Results per page (default 20).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if action_id <= 0:
            return {"error": "action_id is required"}

        params: dict[str, Any] = {"per_page": per_page}
        if level > 0:
            params["level"] = level

        data = _get(f"{base_url}/actions/{action_id}/logs", headers, params)
        if "error" in data:
            return data

        logs = data.get("action_logs", [])
        return {
            "count": len(logs),
            "logs": [
                {
                    "id": item.get("id"),
                    "level": item.get("level"),
                    "message": item.get("message"),
                    "created_at": item.get("created_at"),
                }
                for item in logs
            ],
        }
