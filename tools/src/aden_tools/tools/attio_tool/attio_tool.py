"""
Attio CRM Tool - Manage records, objects, lists, notes, and tasks.

Supports:
- Attio OAuth2 access token or API key (ATTIO_API_KEY)
- Records (People, Companies, Deals, custom objects)
- Lists and Entries
- Notes and Tasks

API Reference: https://docs.attio.com/rest-api/overview
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

ATTIO_API = "https://api.attio.com/v2"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("attio")
    return os.getenv("ATTIO_API_KEY")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{ATTIO_API}/{endpoint}", headers=_headers(token), params=params, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ATTIO_API_KEY."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code != 200:
            return {"error": f"Attio API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Attio timed out"}
    except Exception as e:
        return {"error": f"Attio request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(f"{ATTIO_API}/{endpoint}", headers=_headers(token), json=body or {}, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ATTIO_API_KEY."}
        if resp.status_code not in (200, 201):
            return {"error": f"Attio API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Attio timed out"}
    except Exception as e:
        return {"error": f"Attio request failed: {e!s}"}


def _patch(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.patch(f"{ATTIO_API}/{endpoint}", headers=_headers(token), json=body or {}, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ATTIO_API_KEY."}
        if resp.status_code != 200:
            return {"error": f"Attio API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Attio timed out"}
    except Exception as e:
        return {"error": f"Attio request failed: {e!s}"}


def _delete(endpoint: str, token: str) -> dict[str, Any]:
    try:
        resp = httpx.delete(f"{ATTIO_API}/{endpoint}", headers=_headers(token), timeout=30.0)
        if resp.status_code not in (200, 204):
            return {"error": f"Attio API error {resp.status_code}: {resp.text[:500]}"}
        return {"status": "deleted"}
    except Exception as e:
        return {"error": f"Attio request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "ATTIO_API_KEY not set",
        "help": "Get an API key at https://app.attio.com/settings/developers",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Attio CRM tools with the MCP server."""

    # ── Objects ──────────────────────────────────────────────────

    @mcp.tool()
    def attio_list_objects() -> dict[str, Any]:
        """
        List all objects (People, Companies, Deals, custom) in the Attio workspace.

        Returns:
            Dict with objects list (api_slug, singular_noun, plural_noun)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("objects", token)
        if "error" in data:
            return data

        objects = []
        for o in data.get("data", []):
            objects.append({
                "api_slug": o.get("api_slug", ""),
                "singular_noun": o.get("singular_noun", ""),
                "plural_noun": o.get("plural_noun", ""),
            })
        return {"objects": objects}

    # ── Records ──────────────────────────────────────────────────

    @mcp.tool()
    def attio_list_records(
        object_slug: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List records for a given object type (people, companies, deals, etc.).

        Args:
            object_slug: Object API slug (e.g. "people", "companies", "deals")
            limit: Number of results (1-500, default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with records list (record_id, created_at, values summary)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not object_slug:
            return {"error": "object_slug is required"}

        body = {"limit": max(1, min(limit, 500)), "offset": offset}
        data = _post(f"objects/{object_slug}/records/query", token, body)
        if "error" in data:
            return data

        records = []
        for r in data.get("data", []):
            rid = r.get("id", {})
            records.append({
                "record_id": rid.get("record_id", ""),
                "object_id": rid.get("object_id", ""),
                "created_at": r.get("created_at", ""),
                "web_url": r.get("web_url", ""),
            })
        return {"object": object_slug, "records": records, "count": len(records)}

    @mcp.tool()
    def attio_search_records(
        object_slug: str,
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search records by name/title across an object type.

        Args:
            object_slug: Object API slug (e.g. "people", "companies", "deals")
            query: Search term
            limit: Max results (1-100, default 20)

        Returns:
            Dict with matching records (record_id, created_at, web_url)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not object_slug:
            return {"error": "object_slug is required"}
        if not query:
            return {"error": "query is required"}

        body: dict[str, Any] = {
            "filter": {"name": query},
            "limit": max(1, min(limit, 100)),
        }
        data = _post(f"objects/{object_slug}/records/query", token, body)
        if "error" in data:
            return data

        records = []
        for r in data.get("data", []):
            rid = r.get("id", {})
            records.append({
                "record_id": rid.get("record_id", ""),
                "created_at": r.get("created_at", ""),
                "web_url": r.get("web_url", ""),
            })
        return {"object": object_slug, "query": query, "results": records}

    @mcp.tool()
    def attio_create_record(
        object_slug: str,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new record for a given object type.

        Args:
            object_slug: Object API slug (e.g. "people", "companies", "deals")
            values: Dict of attribute slug -> value. For people: name, email_addresses.
                    For companies: name, domains. Structure depends on the object.

        Returns:
            Dict with created record_id and web_url
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not object_slug:
            return {"error": "object_slug is required"}
        if not values:
            return {"error": "values dict is required"}

        body = {"data": {"values": values}}
        data = _post(f"objects/{object_slug}/records", token, body)
        if "error" in data:
            return data

        rid = data.get("data", {}).get("id", {})
        return {
            "record_id": rid.get("record_id", ""),
            "web_url": data.get("data", {}).get("web_url", ""),
            "status": "created",
        }

    # ── Lists ────────────────────────────────────────────────────

    @mcp.tool()
    def attio_list_lists() -> dict[str, Any]:
        """
        List all lists in the Attio workspace.

        Returns:
            Dict with lists (id, name, api_slug, parent_object)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("lists", token)
        if "error" in data:
            return data

        lists = []
        for lst in data.get("data", []):
            lists.append({
                "id": lst.get("id", {}).get("list_id", ""),
                "name": lst.get("name", ""),
                "api_slug": lst.get("api_slug", ""),
                "parent_object": lst.get("parent_object", ""),
            })
        return {"lists": lists}

    @mcp.tool()
    def attio_list_entries(
        list_slug: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List entries in an Attio list.

        Args:
            list_slug: List API slug or ID
            limit: Number of results (1-500, default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with entries (entry_id, record_id, created_at)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not list_slug:
            return {"error": "list_slug is required"}

        body = {"limit": max(1, min(limit, 500)), "offset": offset}
        data = _post(f"lists/{list_slug}/entries/query", token, body)
        if "error" in data:
            return data

        entries = []
        for e in data.get("data", []):
            eid = e.get("id", {})
            entries.append({
                "entry_id": eid.get("entry_id", ""),
                "list_id": eid.get("list_id", ""),
                "record_id": e.get("parent_record_id", ""),
                "created_at": e.get("created_at", ""),
            })
        return {"list": list_slug, "entries": entries, "count": len(entries)}

    # ── Notes ────────────────────────────────────────────────────

    @mcp.tool()
    def attio_create_note(
        parent_object: str,
        parent_record_id: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        """
        Create a note attached to a record in Attio.

        Args:
            parent_object: Object API slug (e.g. "people", "companies")
            parent_record_id: Record ID to attach the note to
            title: Note title
            content: Note body (plain text)

        Returns:
            Dict with created note id and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not parent_object or not parent_record_id:
            return {"error": "parent_object and parent_record_id are required"}
        if not title or not content:
            return {"error": "title and content are required"}

        body = {
            "data": {
                "parent_object": parent_object,
                "parent_record_id": parent_record_id,
                "title": title,
                "format": "plaintext",
                "content": content,
            }
        }
        data = _post("notes", token, body)
        if "error" in data:
            return data

        return {
            "note_id": data.get("data", {}).get("id", {}).get("note_id", ""),
            "status": "created",
        }

    # ── Tasks ────────────────────────────────────────────────────

    @mcp.tool()
    def attio_list_tasks(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List tasks in the Attio workspace.

        Args:
            limit: Number of results (1-500, default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with tasks list (task_id, content, is_completed, deadline, assignees)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {"limit": max(1, min(limit, 500)), "offset": offset}
        data = _get("tasks", token, params)
        if "error" in data:
            return data

        tasks = []
        for t in data.get("data", []):
            tasks.append({
                "task_id": t.get("id", {}).get("task_id", ""),
                "content": t.get("content_plaintext", ""),
                "is_completed": t.get("is_completed", False),
                "deadline_at": t.get("deadline_at", ""),
                "assignees": [a.get("referenced_actor_id", "") for a in t.get("assignees", [])],
            })
        return {"tasks": tasks, "count": len(tasks)}
