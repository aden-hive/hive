"""Trello API client used by MCP tools."""

from __future__ import annotations

from typing import Any

import httpx

TRELLO_API_BASE = "https://api.trello.com/1"


class TrelloClient:
    """Lightweight Trello REST API v1 client."""

    def __init__(self, api_key: str, api_token: str, timeout: float = 30.0):
        self._api_key = api_key
        self._api_token = api_token
        self._timeout = timeout

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {"error": "Invalid Trello API key or token"}
        if response.status_code == 403:
            return {
                "error": "Insufficient permissions. Check your Trello token scopes.",
            }
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Trello rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {
                "error": f"Trello API error (HTTP {response.status_code}): {detail}",
            }

        try:
            return response.json()
        except Exception:
            return {"result": response.text}

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"key": self._api_key, "token": self._api_token}
        if params:
            query.update({k: v for k, v in params.items() if v is not None})
        response = httpx.request(
            method,
            f"{TRELLO_API_BASE}{path}",
            params=query,
            timeout=self._timeout,
        )
        return self._handle_response(response)

    def list_boards(
        self,
        member_id: str = "me",
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": ",".join(fields) if fields else "id,name,url",
        }
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", f"/members/{member_id}/boards", params=params)

    def get_member(
        self,
        member_id: str = "me",
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": ",".join(fields) if fields else "id,fullName,username,url",
        }
        return self._request("GET", f"/members/{member_id}", params=params)

    def list_lists(
        self,
        board_id: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": ",".join(fields) if fields else "id,name,closed",
        }
        return self._request("GET", f"/boards/{board_id}/lists", params=params)

    def list_cards(
        self,
        list_id: str,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": ",".join(fields) if fields else "id,name,desc,url",
        }
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", f"/lists/{list_id}/cards", params=params)

    def create_card(
        self,
        list_id: str,
        name: str,
        desc: str | None = None,
        due: str | None = None,
        id_members: list[str] | None = None,
        id_labels: list[str] | None = None,
        pos: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "idList": list_id,
            "name": name,
            "desc": desc,
            "due": due,
            "idMembers": ",".join(id_members) if id_members else None,
            "idLabels": ",".join(id_labels) if id_labels else None,
            "pos": pos,
        }
        return self._request("POST", "/cards", params=params)

    def move_card(
        self,
        card_id: str,
        list_id: str,
        pos: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "idList": list_id,
            "pos": pos,
        }
        return self._request("PUT", f"/cards/{card_id}", params=params)

    def update_card(
        self,
        card_id: str,
        name: str | None = None,
        desc: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
        list_id: str | None = None,
        pos: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "name": name,
            "desc": desc,
            "due": due,
            "closed": closed,
            "idList": list_id,
            "pos": pos,
        }
        return self._request("PUT", f"/cards/{card_id}", params=params)

    def add_comment(self, card_id: str, text: str) -> dict[str, Any]:
        params = {"text": text}
        return self._request("POST", f"/cards/{card_id}/actions/comments", params=params)

    def add_attachment(
        self,
        card_id: str,
        attachment_url: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        params = {"url": attachment_url, "name": name}
        return self._request("POST", f"/cards/{card_id}/attachments", params=params)
