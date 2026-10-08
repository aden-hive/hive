"""PagerDuty REST API v2 integration.

Provides incident management and service listing via the PagerDuty API.
Requires PAGERDUTY_API_KEY and PAGERDUTY_FROM_EMAIL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.pagerduty.com"


def _get_headers(write: bool = False) -> dict | None:
    """Return auth headers or None if credentials missing."""
    api_key = os.getenv("PAGERDUTY_API_KEY", "")
    if not api_key:
        return None
    headers = {
        "Authorization": f"Token token={api_key}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }
    if write:
        from_email = os.getenv("PAGERDUTY_FROM_EMAIL", "")
        if from_email:
            headers["From"] = from_email
    return headers


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(path: str, headers: dict, body: dict) -> dict:
    """Send a POST request."""
    resp = httpx.post(f"{BASE_URL}{path}", headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _put(path: str, headers: dict, body: dict) -> dict:
    """Send a PUT request."""
    resp = httpx.put(f"{BASE_URL}{path}", headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_incident(inc: dict) -> dict:
    """Extract key fields from an incident."""
    return {
        "id": inc.get("id"),
        "incident_number": inc.get("incident_number"),
        "title": inc.get("title"),
        "status": inc.get("status"),
        "urgency": inc.get("urgency"),
        "created_at": inc.get("created_at"),
        "html_url": inc.get("html_url"),
        "service": inc.get("service", {}).get("summary"),
        "service_id": inc.get("service", {}).get("id"),
        "assignments": [a.get("assignee", {}).get("summary") for a in inc.get("assignments", [])],
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register PagerDuty tools."""

    @mcp.tool()
    def pagerduty_list_incidents(
        status: str = "",
        since: str = "",
        until: str = "",
        service_id: str = "",
        urgency: str = "",
        limit: int = 25,
    ) -> dict:
        """List PagerDuty incidents with optional filters.

        Args:
            status: Filter by status: 'triggered', 'acknowledged',
                'resolved'. Comma-separated for multiple.
            since: Start of date range (ISO 8601, e.g. '2024-01-01T00:00:00Z').
            until: End of date range (ISO 8601).
            service_id: Filter by service ID.
            urgency: Filter by urgency: 'high' or 'low'.
            limit: Maximum incidents to return (default 25, max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }

        params: dict[str, Any] = {"limit": min(limit, 100)}
        if status:
            for s in status.split(","):
                params.setdefault("statuses[]", [])
                params["statuses[]"].append(s.strip())
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if service_id:
            params["service_ids[]"] = [service_id]
        if urgency:
            params["urgencies[]"] = [urgency]

        data = _get("/incidents", headers, params)
        if "error" in data:
            return data

        incidents = data.get("incidents", [])
        return {
            "count": len(incidents),
            "more": data.get("more", False),
            "incidents": [_extract_incident(i) for i in incidents],
        }

    @mcp.tool()
    def pagerduty_get_incident(incident_id: str) -> dict:
        """Get details of a specific PagerDuty incident.

        Args:
            incident_id: The incident ID (e.g. 'PT4KHLK').
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }
        if not incident_id:
            return {"error": "incident_id is required"}

        data = _get(f"/incidents/{incident_id}", headers)
        if "error" in data:
            return data

        inc = data.get("incident", {})
        result = _extract_incident(inc)
        body = inc.get("body", {})
        if body:
            result["details"] = body.get("details")
        return result

    @mcp.tool()
    def pagerduty_create_incident(
        title: str,
        service_id: str,
        urgency: str = "high",
        details: str = "",
    ) -> dict:
        """Create a new PagerDuty incident.

        Args:
            title: Incident title/summary.
            service_id: The ID of the service to create the incident on.
            urgency: Incident urgency: 'high' or 'low' (default 'high').
            details: Detailed description of the incident.
        """
        headers = _get_headers(write=True)
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }
        if not title or not service_id:
            return {"error": "title and service_id are required"}

        incident: dict[str, Any] = {
            "type": "incident",
            "title": title,
            "service": {"id": service_id, "type": "service_reference"},
            "urgency": urgency,
        }
        if details:
            incident["body"] = {"type": "incident_body", "details": details}

        data = _post("/incidents", headers, {"incident": incident})
        if "error" in data:
            return data

        inc = data.get("incident", {})
        result = _extract_incident(inc)
        result["result"] = "created"
        return result

    @mcp.tool()
    def pagerduty_update_incident(
        incident_id: str,
        status: str = "",
        resolution: str = "",
    ) -> dict:
        """Update a PagerDuty incident (acknowledge, resolve, etc.).

        Args:
            incident_id: The incident ID to update.
            status: New status: 'acknowledged' or 'resolved'.
            resolution: Resolution message (used when resolving).
        """
        headers = _get_headers(write=True)
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }
        if not incident_id:
            return {"error": "incident_id is required"}
        if not status:
            return {"error": "status is required (acknowledged or resolved)"}

        incident: dict[str, Any] = {
            "type": "incident_reference",
            "status": status,
        }
        if resolution and status == "resolved":
            incident["resolution"] = resolution

        data = _put(f"/incidents/{incident_id}", headers, {"incident": incident})
        if "error" in data:
            return data

        inc = data.get("incident", {})
        return _extract_incident(inc)

    @mcp.tool()
    def pagerduty_list_services(
        query: str = "",
        limit: int = 25,
    ) -> dict:
        """List PagerDuty services.

        Args:
            query: Filter services by name.
            limit: Maximum services to return (default 25, max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }

        params: dict[str, Any] = {"limit": min(limit, 100)}
        if query:
            params["query"] = query

        data = _get("/services", headers, params)
        if "error" in data:
            return data

        services = data.get("services", [])
        return {
            "count": len(services),
            "services": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "status": s.get("status"),
                    "html_url": s.get("html_url"),
                    "created_at": s.get("created_at"),
                    "last_incident_timestamp": s.get("last_incident_timestamp"),
                }
                for s in services
            ],
        }

    @mcp.tool()
    def pagerduty_list_oncalls(
        schedule_id: str = "",
        escalation_policy_id: str = "",
        since: str = "",
        until: str = "",
        limit: int = 25,
    ) -> dict:
        """List current on-call entries.

        Args:
            schedule_id: Filter by schedule ID (optional).
            escalation_policy_id: Filter by escalation policy ID (optional).
            since: Start of date range (ISO 8601, optional).
            until: End of date range (ISO 8601, optional).
            limit: Maximum entries to return (default 25, max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }

        params: dict[str, Any] = {"limit": min(limit, 100)}
        if schedule_id:
            params["schedule_ids[]"] = [schedule_id]
        if escalation_policy_id:
            params["escalation_policy_ids[]"] = [escalation_policy_id]
        if since:
            params["since"] = since
        if until:
            params["until"] = until

        data = _get("/oncalls", headers, params)
        if "error" in data:
            return data

        oncalls = data.get("oncalls", [])
        return {
            "count": len(oncalls),
            "oncalls": [
                {
                    "user_name": (oc.get("user") or {}).get("summary", ""),
                    "user_id": (oc.get("user") or {}).get("id", ""),
                    "schedule_name": (oc.get("schedule") or {}).get("summary", ""),
                    "schedule_id": (oc.get("schedule") or {}).get("id", ""),
                    "escalation_policy": (oc.get("escalation_policy") or {}).get("summary", ""),
                    "escalation_level": oc.get("escalation_level", 0),
                    "start": oc.get("start", ""),
                    "end": oc.get("end", ""),
                }
                for oc in oncalls
            ],
        }

    @mcp.tool()
    def pagerduty_add_incident_note(
        incident_id: str,
        content: str,
    ) -> dict:
        """Add a note to a PagerDuty incident.

        Args:
            incident_id: The incident ID (required).
            content: Note content text (required).
        """
        headers = _get_headers(write=True)
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }
        if not incident_id or not content:
            return {"error": "incident_id and content are required"}

        body = {"note": {"content": content}}
        data = _post(f"/incidents/{incident_id}/notes", headers, body)
        if "error" in data:
            return data

        note = data.get("note", {})
        return {
            "id": note.get("id", ""),
            "content": note.get("content", ""),
            "created_at": note.get("created_at", ""),
            "user": (note.get("user") or {}).get("summary", ""),
            "status": "created",
        }

    @mcp.tool()
    def pagerduty_list_escalation_policies(
        query: str = "",
        limit: int = 25,
    ) -> dict:
        """List PagerDuty escalation policies.

        Args:
            query: Filter by name (optional).
            limit: Maximum results (default 25, max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {
                "error": "PAGERDUTY_API_KEY is required",
                "help": "Set PAGERDUTY_API_KEY environment variable",
            }

        params: dict[str, Any] = {"limit": min(limit, 100)}
        if query:
            params["query"] = query

        data = _get("/escalation_policies", headers, params)
        if "error" in data:
            return data

        policies = data.get("escalation_policies", [])
        return {
            "count": len(policies),
            "escalation_policies": [
                {
                    "id": p.get("id", ""),
                    "name": p.get("name", ""),
                    "description": p.get("description", ""),
                    "num_loops": p.get("num_loops", 0),
                    "teams": [t.get("summary", "") for t in p.get("teams", [])],
                    "escalation_rules_count": len(p.get("escalation_rules", [])),
                }
                for p in policies
            ],
        }
