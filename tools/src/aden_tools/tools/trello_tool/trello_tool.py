"""
Trello Tool - Board, list, and card management via REST API.

Supports:
- Trello API key + token authentication
- Boards, lists, cards CRUD
- Member info

API Reference: https://developer.atlassian.com/cloud/trello/rest/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

BASE_URL = "https://api.trello.com/1"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (api_key, api_token)."""
    if credentials is not None:
        key = credentials.get("trello_key")
        token = credentials.get("trello_token")
        return key, token
    return os.getenv("TRELLO_API_KEY"), os.getenv("TRELLO_TOKEN")


def _request(method: str, path: str, key: str, token: str, **kwargs: Any) -> dict | list:
    """Make a request to the Trello API."""
    params = kwargs.pop("params", {})
    params["key"] = key
    params["token"] = token
    try:
        resp = getattr(httpx, method)(
            f"{BASE_URL}{path}",
            params=params,
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your TRELLO_API_KEY and TRELLO_TOKEN."}
        if resp.status_code == 404:
            return {"error": f"Not found: {path}"}
        if resp.status_code not in (200, 201):
            return {"error": f"Trello API error {resp.status_code}: {resp.text[:500]}"}
        if not resp.content:
            return {}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Trello timed out"}
    except Exception as e:
        return {"error": f"Trello request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "TRELLO_API_KEY and TRELLO_TOKEN not set",
        "help": "Get credentials at https://trello.com/power-ups/admin",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Trello tools with the MCP server."""

    @mcp.tool()
    def trello_list_boards() -> dict[str, Any]:
        """
        List all boards for the authenticated Trello user.

        Returns:
            Dict with boards list (id, name, url, closed)
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()

        data = _request("get", "/members/me/boards", key, token, params={"fields": "id,name,url,closed,dateLastActivity"})
        if isinstance(data, dict) and "error" in data:
            return data

        boards = []
        for b in data if isinstance(data, list) else []:
            boards.append({
                "id": b.get("id", ""),
                "name": b.get("name", ""),
                "url": b.get("url", ""),
                "closed": b.get("closed", False),
                "last_activity": b.get("dateLastActivity", ""),
            })
        return {"boards": boards, "count": len(boards)}

    @mcp.tool()
    def trello_get_board(board_id: str) -> dict[str, Any]:
        """
        Get details about a specific Trello board.

        Args:
            board_id: Board ID

        Returns:
            Dict with board details including lists and member count
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()
        if not board_id:
            return {"error": "board_id is required"}

        data = _request("get", f"/boards/{board_id}", key, token)
        if isinstance(data, dict) and "error" in data:
            return data

        b = data if isinstance(data, dict) else {}
        return {
            "id": b.get("id", ""),
            "name": b.get("name", ""),
            "desc": (b.get("desc", "") or "")[:500],
            "url": b.get("url", ""),
            "closed": b.get("closed", False),
            "last_activity": b.get("dateLastActivity", ""),
        }

    @mcp.tool()
    def trello_get_lists(board_id: str) -> dict[str, Any]:
        """
        Get all lists on a Trello board.

        Args:
            board_id: Board ID

        Returns:
            Dict with lists (id, name, closed, pos)
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()
        if not board_id:
            return {"error": "board_id is required"}

        data = _request("get", f"/boards/{board_id}/lists", key, token, params={"fields": "id,name,closed,pos"})
        if isinstance(data, dict) and "error" in data:
            return data

        lists = []
        for lst in data if isinstance(data, list) else []:
            lists.append({
                "id": lst.get("id", ""),
                "name": lst.get("name", ""),
                "closed": lst.get("closed", False),
            })
        return {"lists": lists, "count": len(lists)}

    @mcp.tool()
    def trello_get_cards(
        list_id: str = "",
        board_id: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Get cards from a list or board.

        Args:
            list_id: List ID to get cards from (preferred)
            board_id: Board ID to get all cards (alternative)
            limit: Max cards (1-1000, default 100)

        Returns:
            Dict with cards list (id, name, desc, due, labels, list_id)
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()
        if not list_id and not board_id:
            return {"error": "list_id or board_id is required"}

        path = f"/lists/{list_id}/cards" if list_id else f"/boards/{board_id}/cards"
        data = _request("get", path, key, token, params={
            "fields": "id,name,desc,closed,due,dueComplete,idList,labels,dateLastActivity",
            "limit": max(1, min(limit, 1000)),
        })
        if isinstance(data, dict) and "error" in data:
            return data

        cards = []
        for c in data if isinstance(data, list) else []:
            cards.append({
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "desc": (c.get("desc", "") or "")[:300],
                "closed": c.get("closed", False),
                "due": c.get("due"),
                "due_complete": c.get("dueComplete", False),
                "list_id": c.get("idList", ""),
                "labels": [l.get("name", "") for l in c.get("labels", [])],
            })
        return {"cards": cards, "count": len(cards)}

    @mcp.tool()
    def trello_create_card(
        list_id: str,
        name: str,
        desc: str = "",
        due: str = "",
        pos: str = "bottom",
    ) -> dict[str, Any]:
        """
        Create a new card in a Trello list.

        Args:
            list_id: List ID to create the card in (required)
            name: Card title (required)
            desc: Card description in markdown (optional)
            due: Due date in ISO 8601 format (optional)
            pos: Position: top, bottom, or positive number (default bottom)

        Returns:
            Dict with created card details
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()
        if not list_id or not name:
            return {"error": "list_id and name are required"}

        params: dict[str, Any] = {"idList": list_id, "name": name, "pos": pos}
        if desc:
            params["desc"] = desc
        if due:
            params["due"] = due

        data = _request("post", "/cards", key, token, params=params)
        if isinstance(data, dict) and "error" in data:
            return data

        c = data if isinstance(data, dict) else {}
        return {
            "id": c.get("id", ""),
            "name": c.get("name", ""),
            "url": c.get("url", ""),
            "status": "created",
        }

    @mcp.tool()
    def trello_update_card(
        card_id: str,
        name: str = "",
        desc: str = "",
        closed: bool | None = None,
        due: str = "",
        list_id: str = "",
    ) -> dict[str, Any]:
        """
        Update an existing Trello card.

        Args:
            card_id: Card ID to update (required)
            name: New card title (optional)
            desc: New description (optional)
            closed: True to archive, False to unarchive (optional)
            due: New due date ISO 8601 or empty to remove (optional)
            list_id: Move card to this list (optional)

        Returns:
            Dict with updated card details
        """
        key, token = _get_credentials(credentials)
        if not key or not token:
            return _auth_error()
        if not card_id:
            return {"error": "card_id is required"}

        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if desc:
            params["desc"] = desc
        if closed is not None:
            params["closed"] = str(closed).lower()
        if due:
            params["due"] = due
        if list_id:
            params["idList"] = list_id

        data = _request("put", f"/cards/{card_id}", key, token, params=params)
        if isinstance(data, dict) and "error" in data:
            return data

        c = data if isinstance(data, dict) else {}
        return {
            "id": c.get("id", ""),
            "name": c.get("name", ""),
            "closed": c.get("closed", False),
            "status": "updated",
        }
