"""
Pipedrive CRM Tool - Manage deals, contacts, organizations, and activities.

Supports:
- Pipedrive API token (PIPEDRIVE_API_TOKEN)
- Requires PIPEDRIVE_DOMAIN (your-company.pipedrive.com subdomain)
- Deals, Persons, Organizations, Activities, Notes, Pipelines

API Reference: https://developers.pipedrive.com/docs/api/v1
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("pipedrive")
    return os.getenv("PIPEDRIVE_API_TOKEN")


def _base_url() -> str:
    domain = os.getenv("PIPEDRIVE_DOMAIN", "")
    if domain:
        domain = domain.rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return f"{domain}/api/v1"
    return "https://api.pipedrive.com/v1"


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        p = {"api_token": token}
        if params:
            p.update(params)
        resp = httpx.get(f"{_base_url()}/{endpoint}", params=p, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your PIPEDRIVE_API_TOKEN."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code != 200:
            return {"error": f"Pipedrive API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Pipedrive timed out"}
    except Exception as e:
        return {"error": f"Pipedrive request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{_base_url()}/{endpoint}",
            params={"api_token": token},
            json=body or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your PIPEDRIVE_API_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Pipedrive API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Pipedrive timed out"}
    except Exception as e:
        return {"error": f"Pipedrive request failed: {e!s}"}


def _put(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.put(
            f"{_base_url()}/{endpoint}",
            params={"api_token": token},
            json=body or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your PIPEDRIVE_API_TOKEN."}
        if resp.status_code != 200:
            return {"error": f"Pipedrive API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Pipedrive timed out"}
    except Exception as e:
        return {"error": f"Pipedrive request failed: {e!s}"}


def _delete(endpoint: str, token: str) -> dict[str, Any]:
    try:
        resp = httpx.delete(
            f"{_base_url()}/{endpoint}",
            params={"api_token": token},
            timeout=30.0,
        )
        if resp.status_code not in (200, 204):
            return {"error": f"Pipedrive API error {resp.status_code}: {resp.text[:500]}"}
        return {"status": "deleted"}
    except Exception as e:
        return {"error": f"Pipedrive request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "PIPEDRIVE_API_TOKEN not set",
        "help": "Get your API token from Pipedrive Settings > Personal preferences > API",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Pipedrive CRM tools with the MCP server."""

    # ── Deals ────────────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_list_deals(
        status: str = "open",
        limit: int = 50,
        start: int = 0,
    ) -> dict[str, Any]:
        """
        List deals from Pipedrive CRM.

        Args:
            status: Filter by status: open, won, lost, deleted, all_not_deleted (default open)
            limit: Number of results (1-500, default 50)
            start: Pagination offset (default 0)

        Returns:
            Dict with deals list (id, title, value, currency,
                status, person_name, org_name, stage_id)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {
            "status": status,
            "limit": max(1, min(limit, 500)),
            "start": start,
        }
        data = _get("deals", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown Pipedrive error")}

        deals = []
        for d in data.get("data") or []:
            deals.append(
                {
                    "id": d.get("id"),
                    "title": d.get("title", ""),
                    "value": d.get("value", 0),
                    "currency": d.get("currency", ""),
                    "status": d.get("status", ""),
                    "person_name": (d.get("person_id") or {}).get("name", ""),
                    "org_name": (d.get("org_id") or {}).get("name", ""),
                    "stage_id": d.get("stage_id"),
                    "add_time": d.get("add_time", ""),
                }
            )
        return {"deals": deals, "count": len(deals)}

    @mcp.tool()
    def pipedrive_get_deal(deal_id: int) -> dict[str, Any]:
        """
        Get details of a specific Pipedrive deal.

        Args:
            deal_id: The deal ID

        Returns:
            Dict with deal details including title, value, status, person, org, stage, pipeline
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not deal_id:
            return {"error": "deal_id is required"}

        data = _get(f"deals/{deal_id}", token)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Deal not found")}

        d = data.get("data", {})
        return {
            "id": d.get("id"),
            "title": d.get("title", ""),
            "value": d.get("value", 0),
            "currency": d.get("currency", ""),
            "status": d.get("status", ""),
            "person_name": (d.get("person_id") or {}).get("name", ""),
            "org_name": (d.get("org_id") or {}).get("name", ""),
            "stage_id": d.get("stage_id"),
            "pipeline_id": d.get("pipeline_id"),
            "expected_close_date": d.get("expected_close_date", ""),
            "probability": d.get("probability"),
            "add_time": d.get("add_time", ""),
            "won_time": d.get("won_time", ""),
            "lost_time": d.get("lost_time", ""),
            "lost_reason": d.get("lost_reason", ""),
        }

    @mcp.tool()
    def pipedrive_create_deal(
        title: str,
        value: float = 0,
        currency: str = "USD",
        person_id: int = 0,
        org_id: int = 0,
        stage_id: int = 0,
    ) -> dict[str, Any]:
        """
        Create a new deal in Pipedrive.

        Args:
            title: Deal title (required)
            value: Deal monetary value (default 0)
            currency: Currency code (default USD)
            person_id: Associated person/contact ID (optional)
            org_id: Associated organization ID (optional)
            stage_id: Pipeline stage ID (optional, defaults to first stage)

        Returns:
            Dict with created deal id and title
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not title:
            return {"error": "title is required"}

        body: dict[str, Any] = {"title": title}
        if value:
            body["value"] = value
            body["currency"] = currency
        if person_id:
            body["person_id"] = person_id
        if org_id:
            body["org_id"] = org_id
        if stage_id:
            body["stage_id"] = stage_id

        data = _post("deals", token, body)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Failed to create deal")}

        d = data.get("data", {})
        return {"id": d.get("id"), "title": d.get("title", ""), "status": "created"}

    # ── Persons (Contacts) ───────────────────────────────────────

    @mcp.tool()
    def pipedrive_list_persons(
        limit: int = 50,
        start: int = 0,
    ) -> dict[str, Any]:
        """
        List persons (contacts) from Pipedrive.

        Args:
            limit: Number of results (1-500, default 50)
            start: Pagination offset (default 0)

        Returns:
            Dict with persons list (id, name, email, phone, org_name, open_deals_count)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {"limit": max(1, min(limit, 500)), "start": start}
        data = _get("persons", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown error")}

        persons = []
        for p in data.get("data") or []:
            emails = p.get("email", [])
            phones = p.get("phone", [])
            persons.append(
                {
                    "id": p.get("id"),
                    "name": p.get("name", ""),
                    "email": emails[0].get("value", "") if emails else "",
                    "phone": phones[0].get("value", "") if phones else "",
                    "org_name": (p.get("org_id") or {}).get("name", ""),
                    "open_deals_count": p.get("open_deals_count", 0),
                }
            )
        return {"persons": persons, "count": len(persons)}

    @mcp.tool()
    def pipedrive_search_persons(
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search for persons in Pipedrive by name, email, or phone.

        Args:
            query: Search term (name, email, or phone)
            limit: Number of results (1-100, default 20)

        Returns:
            Dict with matching persons (id, name, email, phone, org_name)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        params = {"term": query, "limit": max(1, min(limit, 100))}
        data = _get("persons/search", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Search failed")}

        results = []
        for item in (data.get("data") or {}).get("items", []):
            p = item.get("item", {})
            emails = p.get("emails", [])
            phones = p.get("phones", [])
            results.append(
                {
                    "id": p.get("id"),
                    "name": p.get("name", ""),
                    "email": emails[0] if emails else "",
                    "phone": phones[0] if phones else "",
                    "org_name": (p.get("organization") or {}).get("name", ""),
                }
            )
        return {"query": query, "results": results}

    # ── Organizations ────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_list_organizations(
        limit: int = 50,
        start: int = 0,
    ) -> dict[str, Any]:
        """
        List organizations from Pipedrive.

        Args:
            limit: Number of results (1-500, default 50)
            start: Pagination offset (default 0)

        Returns:
            Dict with organizations list (id, name, address, open_deals_count, people_count)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params = {"limit": max(1, min(limit, 500)), "start": start}
        data = _get("organizations", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown error")}

        orgs = []
        for o in data.get("data") or []:
            orgs.append(
                {
                    "id": o.get("id"),
                    "name": o.get("name", ""),
                    "address": o.get("address", ""),
                    "open_deals_count": o.get("open_deals_count", 0),
                    "people_count": o.get("people_count", 0),
                }
            )
        return {"organizations": orgs, "count": len(orgs)}

    # ── Activities ───────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_list_activities(
        done: str = "",
        activity_type: str = "",
        limit: int = 50,
        start: int = 0,
    ) -> dict[str, Any]:
        """
        List activities (calls, meetings, tasks, etc.) from Pipedrive.

        Args:
            done: Filter: "0" for undone, "1" for done, "" for all (default all)
            activity_type: Filter by type: call, meeting, task, deadline, email, lunch
            limit: Number of results (1-500, default 50)
            start: Pagination offset (default 0)

        Returns:
            Dict with activities list (id, subject, type, done, due_date, deal_title, person_name)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "limit": max(1, min(limit, 500)),
            "start": start,
        }
        if done:
            params["done"] = done
        if activity_type:
            params["type"] = activity_type

        data = _get("activities", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown error")}

        activities = []
        for a in data.get("data") or []:
            activities.append(
                {
                    "id": a.get("id"),
                    "subject": a.get("subject", ""),
                    "type": a.get("type", ""),
                    "done": a.get("done", False),
                    "due_date": a.get("due_date", ""),
                    "due_time": a.get("due_time", ""),
                    "deal_title": a.get("deal_title", ""),
                    "person_name": a.get("person_name", ""),
                    "org_name": a.get("org_name", ""),
                    "note": a.get("note", "")[:200] if a.get("note") else "",
                }
            )
        return {"activities": activities, "count": len(activities)}

    # ── Pipelines ────────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_list_pipelines() -> dict[str, Any]:
        """
        List all sales pipelines in Pipedrive.

        Returns:
            Dict with pipelines list (id, name, active, deal_probability, order_nr)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("pipelines", token)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown error")}

        pipelines = []
        for p in data.get("data") or []:
            pipelines.append(
                {
                    "id": p.get("id"),
                    "name": p.get("name", ""),
                    "active": p.get("active", False),
                    "deal_probability": p.get("deal_probability", False),
                    "order_nr": p.get("order_nr", 0),
                }
            )
        return {"pipelines": pipelines}

    @mcp.tool()
    def pipedrive_list_stages(pipeline_id: int = 0) -> dict[str, Any]:
        """
        List pipeline stages in Pipedrive.

        Args:
            pipeline_id: Filter by pipeline ID (optional, 0 returns all stages)

        Returns:
            Dict with stages list (id, name, pipeline_id, order_nr, deals_summary)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id

        data = _get("stages", token, params)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Unknown error")}

        stages = []
        for s in data.get("data") or []:
            stages.append(
                {
                    "id": s.get("id"),
                    "name": s.get("name", ""),
                    "pipeline_id": s.get("pipeline_id"),
                    "order_nr": s.get("order_nr", 0),
                    "active_flag": s.get("active_flag", True),
                }
            )
        return {"stages": stages}

    # ── Notes ────────────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_add_note(
        content: str,
        deal_id: int = 0,
        person_id: int = 0,
        org_id: int = 0,
    ) -> dict[str, Any]:
        """
        Add a note to a deal, person, or organization in Pipedrive.

        Args:
            content: Note content (HTML supported)
            deal_id: Attach to this deal (optional)
            person_id: Attach to this person (optional)
            org_id: Attach to this organization (optional)

        Returns:
            Dict with created note id and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not content:
            return {"error": "content is required"}
        if not (deal_id or person_id or org_id):
            return {"error": "At least one of deal_id, person_id, or org_id is required"}

        body: dict[str, Any] = {"content": content}
        if deal_id:
            body["deal_id"] = deal_id
        if person_id:
            body["person_id"] = person_id
        if org_id:
            body["org_id"] = org_id

        data = _post("notes", token, body)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Failed to add note")}

        return {"id": data.get("data", {}).get("id"), "status": "created"}

    # ── Deal Updates ──────────────────────────────────────────────

    @mcp.tool()
    def pipedrive_update_deal(
        deal_id: int,
        title: str = "",
        value: float = 0,
        currency: str = "",
        status: str = "",
        stage_id: int = 0,
        expected_close_date: str = "",
        lost_reason: str = "",
    ) -> dict[str, Any]:
        """
        Update an existing Pipedrive deal.

        Args:
            deal_id: Deal ID (required)
            title: New deal title (optional)
            value: New deal value (optional)
            currency: Currency code e.g. "USD" (optional)
            status: New status: open, won, lost, deleted (optional)
            stage_id: Move to this pipeline stage ID (optional)
            expected_close_date: Expected close date YYYY-MM-DD (optional)
            lost_reason: Reason for loss when setting status to lost (optional)

        Returns:
            Dict with updated deal (id, title, status) or error
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not deal_id:
            return {"error": "deal_id is required"}

        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        if value:
            body["value"] = value
        if currency:
            body["currency"] = currency
        if status:
            body["status"] = status
        if stage_id:
            body["stage_id"] = stage_id
        if expected_close_date:
            body["expected_close_date"] = expected_close_date
        if lost_reason:
            body["lost_reason"] = lost_reason

        if not body:
            return {"error": "At least one field to update is required"}

        data = _put(f"deals/{deal_id}", token, body)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Failed to update deal")}

        d = data.get("data", {})
        return {
            "id": d.get("id"),
            "title": d.get("title", ""),
            "status": d.get("status", ""),
            "result": "updated",
        }

    # ── Person Creation ───────────────────────────────────────────

    @mcp.tool()
    def pipedrive_create_person(
        name: str,
        email: str = "",
        phone: str = "",
        org_id: int = 0,
    ) -> dict[str, Any]:
        """
        Create a new person (contact) in Pipedrive.

        Args:
            name: Person's full name (required)
            email: Email address (optional)
            phone: Phone number (optional)
            org_id: Associated organization ID (optional)

        Returns:
            Dict with created person (id, name) or error
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not name:
            return {"error": "name is required"}

        body: dict[str, Any] = {"name": name}
        if email:
            body["email"] = [{"value": email, "primary": True, "label": "work"}]
        if phone:
            body["phone"] = [{"value": phone, "primary": True, "label": "work"}]
        if org_id:
            body["org_id"] = org_id

        data = _post("persons", token, body)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Failed to create person")}

        p = data.get("data", {})
        return {"id": p.get("id"), "name": p.get("name", ""), "status": "created"}

    # ── Activity Creation ─────────────────────────────────────────

    @mcp.tool()
    def pipedrive_create_activity(
        subject: str,
        activity_type: str = "task",
        due_date: str = "",
        due_time: str = "",
        deal_id: int = 0,
        person_id: int = 0,
        org_id: int = 0,
        note: str = "",
    ) -> dict[str, Any]:
        """
        Create a new activity (call, meeting, task, etc.) in Pipedrive.

        Args:
            subject: Activity subject/title (required)
            activity_type: Type: call, meeting, task, deadline, email, lunch (default task)
            due_date: Due date YYYY-MM-DD (optional)
            due_time: Due time HH:MM (optional)
            deal_id: Associated deal ID (optional)
            person_id: Associated person ID (optional)
            org_id: Associated organization ID (optional)
            note: Activity note/description (optional)

        Returns:
            Dict with created activity (id, subject, type) or error
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not subject:
            return {"error": "subject is required"}

        body: dict[str, Any] = {"subject": subject, "type": activity_type}
        if due_date:
            body["due_date"] = due_date
        if due_time:
            body["due_time"] = due_time
        if deal_id:
            body["deal_id"] = deal_id
        if person_id:
            body["person_id"] = person_id
        if org_id:
            body["org_id"] = org_id
        if note:
            body["note"] = note

        data = _post("activities", token, body)
        if "error" in data:
            return data
        if not data.get("success"):
            return {"error": data.get("error", "Failed to create activity")}

        a = data.get("data", {})
        return {
            "id": a.get("id"),
            "subject": a.get("subject", ""),
            "type": a.get("type", ""),
            "status": "created",
        }
