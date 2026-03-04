"""
Zendesk Tool - Ticket management and search via Zendesk Support API.

Supports:
- Zendesk Cloud (Basic auth with email/token + API token)
- Tickets: list, get, create, update, search

API Reference: https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_credentials(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (subdomain, email, api_token)."""
    if credentials is not None:
        subdomain = credentials.get("zendesk_subdomain")
        email = credentials.get("zendesk_email")
        token = credentials.get("zendesk_token")
        return subdomain, email, token
    return (
        os.getenv("ZENDESK_SUBDOMAIN"),
        os.getenv("ZENDESK_EMAIL"),
        os.getenv("ZENDESK_API_TOKEN"),
    )


def _base_url(subdomain: str) -> str:
    return f"https://{subdomain}.zendesk.com/api/v2"


def _auth_header(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}/token:{token}".encode()).decode()
    return f"Basic {encoded}"


def _request(method: str, url: str, email: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a request to the Zendesk API."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = _auth_header(email, token)
    headers.setdefault("Content-Type", "application/json")
    try:
        resp = getattr(httpx, method)(
            url,
            headers=headers,
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Zendesk credentials."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Check your Zendesk permissions."}
        if resp.status_code == 404:
            return {"error": "Not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201):
            return {"error": f"Zendesk API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Zendesk timed out"}
    except Exception as e:
        return {"error": f"Zendesk request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN not set",
        "help": "Create an API token in Zendesk Admin > Apps and integrations > APIs > Zendesk API",
    }


def _extract_ticket(t: dict) -> dict[str, Any]:
    return {
        "id": t.get("id"),
        "subject": t.get("subject", ""),
        "description": (t.get("description") or "")[:500],
        "status": t.get("status", ""),
        "priority": t.get("priority", ""),
        "type": t.get("type", ""),
        "tags": t.get("tags", []),
        "requester_id": t.get("requester_id"),
        "assignee_id": t.get("assignee_id"),
        "created_at": t.get("created_at", ""),
        "updated_at": t.get("updated_at", ""),
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Zendesk tools with the MCP server."""

    @mcp.tool()
    def zendesk_list_tickets(
        page_size: int = 25,
    ) -> dict[str, Any]:
        """
        List tickets in Zendesk.

        Args:
            page_size: Number of tickets per page (1-100, default 25)

        Returns:
            Dict with tickets list (id, subject, status, priority, tags)
        """
        subdomain, email, token = _get_credentials(credentials)
        if not subdomain or not email or not token:
            return _auth_error()

        url = f"{_base_url(subdomain)}/tickets"
        params = {"page[size]": max(1, min(page_size, 100))}
        data = _request("get", url, email, token, params=params)
        if "error" in data:
            return data

        tickets = [_extract_ticket(t) for t in data.get("tickets", [])]
        return {"tickets": tickets, "count": len(tickets)}

    @mcp.tool()
    def zendesk_get_ticket(ticket_id: int) -> dict[str, Any]:
        """
        Get details about a specific Zendesk ticket.

        Args:
            ticket_id: Zendesk ticket ID (required)

        Returns:
            Dict with ticket details (subject, description, status, priority, etc.)
        """
        subdomain, email, token = _get_credentials(credentials)
        if not subdomain or not email or not token:
            return _auth_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        url = f"{_base_url(subdomain)}/tickets/{ticket_id}"
        data = _request("get", url, email, token)
        if "error" in data:
            return data

        return _extract_ticket(data.get("ticket", {}))

    @mcp.tool()
    def zendesk_create_ticket(
        subject: str,
        body: str,
        priority: str = "normal",
        ticket_type: str = "",
        tags: str = "",
    ) -> dict[str, Any]:
        """
        Create a new Zendesk ticket.

        Args:
            subject: Ticket subject (required)
            body: Ticket description/first comment (required)
            priority: Priority: urgent, high, normal, low (default normal)
            ticket_type: Type: question, incident, problem, task (optional)
            tags: Comma-separated tags (optional)

        Returns:
            Dict with created ticket (id, subject, status)
        """
        subdomain, email, token = _get_credentials(credentials)
        if not subdomain or not email or not token:
            return _auth_error()
        if not subject or not body:
            return {"error": "subject and body are required"}

        ticket: dict[str, Any] = {
            "subject": subject,
            "comment": {"body": body},
            "priority": priority,
        }
        if ticket_type:
            ticket["type"] = ticket_type
        if tags:
            ticket["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        url = f"{_base_url(subdomain)}/tickets"
        data = _request("post", url, email, token, json={"ticket": ticket})
        if "error" in data:
            return data

        t = data.get("ticket", {})
        return {
            "id": t.get("id"),
            "subject": t.get("subject", ""),
            "status": t.get("status", ""),
            "url": f"https://{subdomain}.zendesk.com/agent/tickets/{t.get('id', '')}",
            "result": "created",
        }

    @mcp.tool()
    def zendesk_update_ticket(
        ticket_id: int,
        status: str = "",
        priority: str = "",
        comment: str = "",
        comment_public: bool = True,
        tags: str = "",
    ) -> dict[str, Any]:
        """
        Update a Zendesk ticket and optionally add a comment.

        Args:
            ticket_id: Zendesk ticket ID (required)
            status: New status: new, open, pending, hold, solved, closed (optional)
            priority: New priority: urgent, high, normal, low (optional)
            comment: Add a comment to the ticket (optional)
            comment_public: Whether comment is visible to requester (default True)
            tags: Replace tags with comma-separated list (optional)

        Returns:
            Dict with updated ticket details
        """
        subdomain, email, token = _get_credentials(credentials)
        if not subdomain or not email or not token:
            return _auth_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        ticket: dict[str, Any] = {}
        if status:
            ticket["status"] = status
        if priority:
            ticket["priority"] = priority
        if comment:
            ticket["comment"] = {"body": comment, "public": comment_public}
        if tags:
            ticket["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not ticket:
            return {"error": "At least one field to update is required"}

        url = f"{_base_url(subdomain)}/tickets/{ticket_id}"
        data = _request("put", url, email, token, json={"ticket": ticket})
        if "error" in data:
            return data

        return _extract_ticket(data.get("ticket", {}))

    @mcp.tool()
    def zendesk_search_tickets(
        query: str,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        Search Zendesk tickets using Zendesk search syntax.

        Args:
            query: Search query e.g. "status:open priority:urgent" (required)
            sort_by: Sort by: updated_at, created_at, priority, status (default updated_at)
            sort_order: Sort order: asc, desc (default desc)

        Returns:
            Dict with matching tickets (id, subject, status)
        """
        subdomain, email, token = _get_credentials(credentials)
        if not subdomain or not email or not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        full_query = f"type:ticket {query}" if "type:" not in query else query
        url = f"{_base_url(subdomain)}/search"
        params = {"query": full_query, "sort_by": sort_by, "sort_order": sort_order}
        data = _request("get", url, email, token, params=params)
        if "error" in data:
            return data

        results = []
        for r in data.get("results", []):
            results.append(
                {
                    "id": r.get("id"),
                    "subject": r.get("subject", ""),
                    "status": r.get("status", ""),
                    "priority": r.get("priority", ""),
                }
            )
        return {"results": results, "count": data.get("count", len(results))}
