"""
Freshdesk tool — tickets, contacts, agents, groups via Freshdesk API v2.

Use when an agent needs to query or modify support data in Freshdesk.
Auth: Basic (API key as username, X as password). Domain from credentials/env.
API: https://developers.freshdesk.com/api/
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_api_key(credentials: CredentialStoreAdapter | None) -> str | None:
    """Return Freshdesk API key from credential store or env."""
    if credentials is not None:
        return credentials.get("freshdesk")
    return os.getenv("FRESHDESK_API_KEY")


def _get_domain(credentials: CredentialStoreAdapter | None) -> str | None:
    """Return Freshdesk domain from credential store or env (e.g. acme.freshdesk.com)."""
    if credentials is not None:
        value = credentials.get("freshdesk_domain")
        if value:
            return value.strip()
    value = os.getenv("FRESHDESK_DOMAIN")
    return value.strip() if value else None


def _base_url(domain: str) -> str:
    """Build base API URL from domain (e.g. acme.freshdesk.com)."""
    domain = domain.strip()
    if domain.startswith("https://"):
        domain = domain[len("https://") :]
    if domain.startswith("http://"):
        domain = domain[len("http://") :]
    return f"https://{domain}/api/v2"


def _auth_header(api_key: str) -> str:
    """Build Basic auth header for Freshdesk API key."""
    encoded = base64.b64encode(f"{api_key}:X".encode()).decode()
    return f"Basic {encoded}"


def _request(
    method: str,
    url: str,
    api_key: str,
    **kwargs: Any,
) -> dict[str, Any] | list[Any]:
    """Make a request to the Freshdesk API with standard error handling."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = _auth_header(api_key)
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    try:
        if method == "get":
            resp = httpx.get(
                url,
                headers=headers,
                timeout=30.0,
                **kwargs,
            )
        elif method == "post":
            resp = httpx.post(
                url,
                headers=headers,
                timeout=30.0,
                **kwargs,
            )
        elif method == "put":
            resp = httpx.put(
                url,
                headers=headers,
                timeout=30.0,
                **kwargs,
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Freshdesk API key."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Check your Freshdesk permissions."}
        if resp.status_code == 404:
            return {"error": "Not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201, 202):
            return {"error": f"Freshdesk API error {resp.status_code}: {resp.text[:500]}"}
        try:
            return resp.json()
        except Exception:
            return {"error": "Failed to parse Freshdesk response"}
    except httpx.TimeoutException:
        return {"error": "Request to Freshdesk timed out"}
    except Exception as e:  # pragma: no cover
        return {"error": f"Freshdesk request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    """Return standardized missing-API-key error payload."""
    return {
        "error": "FRESHDESK_API_KEY environment variable not set",
        "help": "Get your API key from Freshdesk profile settings and set "
        "FRESHDESK_API_KEY, or configure it via the credential store.",
    }


def _domain_error() -> dict[str, Any]:
    """Return standardized missing-domain error payload."""
    return {
        "error": "FRESHDESK_DOMAIN is required",
        "help": "Set FRESHDESK_DOMAIN (e.g. acme.freshdesk.com) or configure freshdesk_domain.",
    }


def _extract_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    """Normalize Freshdesk ticket into a compact dict."""
    return {
        "id": ticket.get("id"),
        "subject": ticket.get("subject", ""),
        "description": (ticket.get("description") or "")[:500],
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "type": ticket.get("type"),
        "tags": ticket.get("tags", []),
        "requester_id": ticket.get("requester_id"),
        "responder_id": ticket.get("responder_id"),
        "created_at": ticket.get("created_at"),
        "updated_at": ticket.get("updated_at"),
    }


def _extract_contact(contact: dict[str, Any]) -> dict[str, Any]:
    """Normalize Freshdesk contact into a compact dict."""
    return {
        "id": contact.get("id"),
        "name": contact.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "mobile": contact.get("mobile"),
        "company_id": contact.get("company_id"),
        "active": contact.get("active"),
        "created_at": contact.get("created_at"),
        "updated_at": contact.get("updated_at"),
    }


def _extract_agent(agent: dict[str, Any]) -> dict[str, Any]:
    """Normalize Freshdesk agent into a compact dict."""
    return {
        "id": agent.get("id"),
        "contact_id": agent.get("contact_id"),
        "email": agent.get("email"),
        "occasional": agent.get("occasional"),
        "available": agent.get("available"),
        "name": agent.get("contact", {}).get("name"),
    }


def _extract_group(group: dict[str, Any]) -> dict[str, Any]:
    """Normalize Freshdesk group into a compact dict."""
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "description": group.get("description"),
        "unassigned_for": group.get("unassigned_for"),
        "created_at": group.get("created_at"),
        "updated_at": group.get("updated_at"),
    }


def _extract_company(company: dict[str, Any]) -> dict[str, Any]:
    """Normalize Freshdesk company into a compact dict."""
    return {
        "id": company.get("id"),
        "name": company.get("name"),
        "description": company.get("description"),
        "domains": company.get("domains", []),
        "note": company.get("note"),
        "created_at": company.get("created_at"),
        "updated_at": company.get("updated_at"),
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Freshdesk tools with the MCP server."""

    @mcp.tool()
    def freshdesk_list_tickets(
        page: int = 1,
        per_page: int = 30,
        filter: str | None = None,
        updated_since: str | None = None,
    ) -> dict[str, Any]:
        """
        List tickets in Freshdesk.

        Use this to get a page of tickets for digests, triage, or reporting.

        Args:
            page: Page number (1-based, default 1)
            per_page: Tickets per page (1-100, default 30)
            filter: Optional built-in filter name (e.g. \"new_and_my_open\")
            updated_since: Optional ISO8601 timestamp to list tickets updated since

        Returns:
            Dict with tickets list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()

        url = f"{_base_url(domain)}/tickets"
        per_page_clamped = max(1, min(per_page, 100))
        params: dict[str, Any] = {"page": max(1, page), "per_page": per_page_clamped}
        if filter:
            params["filter"] = filter
        if updated_since:
            params["updated_since"] = updated_since

        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        tickets = [_extract_ticket(t) for t in data]
        return {"tickets": tickets, "count": len(tickets)}

    @mcp.tool()
    def freshdesk_filter_tickets(
        query: str,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        Search/filter Freshdesk tickets by query.

        Use Freshdesk query syntax (e.g. "priority:3", "status:2"). API requires
        the query enclosed in double quotes; the tool adds them if missing.

        Args:
            query: Search query (e.g. "priority:3", "status:2 OR status:3");
                tool wraps in double quotes for API.
            page: Page number (1-10 for search API, default 1)

        Returns:
            Dict with results list, total count, and count on this page.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not query:
            return {"error": "query is required"}

        query_value = query.strip()
        if not (query_value.startswith('"') and query_value.endswith('"')):
            query_value = f'"{query_value}"'

        url = f"{_base_url(domain)}/search/tickets"
        params = {"query": query_value, "page": max(1, min(page, 10))}
        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        results = data.get("results", [])
        total = data.get("total", len(results))
        tickets = [_extract_ticket(t) for t in results]
        return {"tickets": tickets, "count": len(tickets), "total": total}

    @mcp.tool()
    def freshdesk_list_ticket_conversations(
        ticket_id: int,
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        """
        List conversations (replies and notes) for a Freshdesk ticket.

        Args:
            ticket_id: Freshdesk ticket ID (required)
            page: Page number (default 1)
            per_page: Items per page (default 30)

        Returns:
            Dict with conversations list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        url = f"{_base_url(domain)}/tickets/{ticket_id}/conversations"
        params = {"page": max(1, page), "per_page": max(1, min(per_page, 100))}
        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        raw = data if isinstance(data, list) else data.get("conversations", []) or []
        convos = [
            {
                "id": c.get("id"),
                "body_text": (c.get("body_text") or "")[:500],
                "private": c.get("private"),
                "user_id": c.get("user_id"),
                "created_at": c.get("created_at"),
            }
            for c in raw
        ]
        return {"conversations": convos, "count": len(convos)}

    @mcp.tool()
    def freshdesk_get_ticket(
        ticket_id: int,
    ) -> dict[str, Any]:
        """
        Get details about a specific Freshdesk ticket.

        Args:
            ticket_id: Freshdesk ticket ID (required)

        Returns:
            Dict with ticket details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        url = f"{_base_url(domain)}/tickets/{ticket_id}"
        data = _request("get", url, api_key)
        if "error" in data:
            return data

        return _extract_ticket(data)

    @mcp.tool()
    def freshdesk_create_ticket(
        email: str,
        subject: str,
        description: str,
        priority: int | None = None,
        status: int | None = None,
        tags: str = "",
    ) -> dict[str, Any]:
        """
        Create a new Freshdesk ticket.

        Args:
            email: Requester email address (required)
            subject: Ticket subject (required)
            description: Ticket description/first message (required)
            priority: Optional priority (1-4) as defined in Freshdesk
            status: Optional status (e.g. 2=open, 3=pending, 4=resolved)
            tags: Optional comma-separated tags

        Returns:
            Dict with created ticket id, subject, status, and URL.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not email or not subject or not description:
            return {"error": "email, subject, and description are required"}

        payload: dict[str, Any] = {
            "email": email,
            "subject": subject,
            "description": description,
        }
        if priority is not None:
            payload["priority"] = priority
        if status is not None:
            payload["status"] = status
        if tags:
            payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        url = f"{_base_url(domain)}/tickets"
        data = _request("post", url, api_key, json=payload)
        if "error" in data:
            return data

        ticket_id = data.get("id")
        return {
            "id": ticket_id,
            "subject": data.get("subject", ""),
            "status": data.get("status"),
            "url": f"https://{domain}/a/tickets/{ticket_id}" if ticket_id else None,
            "result": "created",
        }

    @mcp.tool()
    def freshdesk_update_ticket(
        ticket_id: int,
        status: int | None = None,
        priority: int | None = None,
        tags: str = "",
        note: str = "",
        note_private: bool = True,
    ) -> dict[str, Any]:
        """
        Update a Freshdesk ticket and optionally add a note.

        Args:
            ticket_id: Freshdesk ticket ID (required)
            status: Optional new status code
            priority: Optional new priority code
            tags: Optional comma-separated tags (replaces existing tags)
            note: Optional note to add to the ticket
            note_private: Whether the note is private (default True)

        Returns:
            Dict with updated ticket details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if priority is not None:
            updates["priority"] = priority
        if tags:
            updates["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not updates and not note:
            return {"error": "At least one field (status, priority, tags, note) is required"}

        if updates:
            url = f"{_base_url(domain)}/tickets/{ticket_id}"
            data = _request("put", url, api_key, json=updates)
            if "error" in data:
                return data
            ticket_data = data
        else:
            url = f"{_base_url(domain)}/tickets/{ticket_id}"
            ticket_data = _request("get", url, api_key)
            if "error" in ticket_data:
                return ticket_data

        result = _extract_ticket(ticket_data)

        if note:
            notes_url = f"{_base_url(domain)}/tickets/{ticket_id}/notes"
            note_payload = {"body": note, "private": note_private}
            note_result = _request("post", notes_url, api_key, json=note_payload)
            if "error" in note_result:
                result["note_error"] = note_result["error"]

        return result

    @mcp.tool()
    def freshdesk_add_ticket_reply(
        ticket_id: int,
        body: str,
        public: bool = True,
        from_email: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a reply to a Freshdesk ticket.

        Args:
            ticket_id: Freshdesk ticket ID (required)
            body: Reply body (required)
            public: Whether reply is visible to requester (default True)
            from_email: Optional agent email; if omitted, API key user is used

        Returns:
            Dict with reply metadata or error.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not ticket_id:
            return {"error": "ticket_id is required"}
        if not body:
            return {"error": "body is required"}

        if public:
            payload: dict[str, Any] = {"body": body}
            if from_email is not None:
                payload["from_email"] = from_email
            url = f"{_base_url(domain)}/tickets/{ticket_id}/reply"
        else:
            payload = {"body": body, "private": True}
            url = f"{_base_url(domain)}/tickets/{ticket_id}/notes"

        data = _request("post", url, api_key, json=payload)
        if "error" in data:
            return data

        return {
            "id": data.get("id"),
            "body": data.get("body") or data.get("body_text", ""),
            "public": public,
            "created_at": data.get("created_at"),
        }

    @mcp.tool()
    def freshdesk_list_contacts(
        page: int = 1,
        per_page: int = 30,
        email: str | None = None,
    ) -> dict[str, Any]:
        """
        List contacts in Freshdesk, optionally filtered by email.

        Args:
            page: Page number (1-based, default 1)
            per_page: Contacts per page (1-100, default 30)
            email: Optional email filter to return matching contacts

        Returns:
            Dict with contacts list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()

        url = f"{_base_url(domain)}/contacts"
        per_page_clamped = max(1, min(per_page, 100))
        params: dict[str, Any] = {"page": max(1, page), "per_page": per_page_clamped}
        if email:
            params["email"] = email

        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        contacts = [_extract_contact(c) for c in data]
        return {"contacts": contacts, "count": len(contacts)}

    @mcp.tool()
    def freshdesk_get_contact(
        contact_id: int | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """
        Get a Freshdesk contact by ID or email.

        Args:
            contact_id: Contact ID (preferred)
            email: Contact email (used when contact_id is not provided)

        Returns:
            Dict with contact details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not contact_id and not email:
            return {"error": "contact_id or email is required"}

        if contact_id:
            url = f"{_base_url(domain)}/contacts/{contact_id}"
            data = _request("get", url, api_key)
            if "error" in data:
                return data
            return _extract_contact(data)

        url = f"{_base_url(domain)}/contacts"
        params = {"email": email}
        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data
        if not data:
            return {"error": "Contact not found"}

        contact = data[0] if isinstance(data, list) else data
        return _extract_contact(contact)

    @mcp.tool()
    def freshdesk_create_contact(
        email: str,
        name: str | None = None,
        phone: str | None = None,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a new Freshdesk contact.

        Args:
            email: Contact email (required)
            name: Optional name
            phone: Optional phone number
            company_id: Optional company ID

        Returns:
            Dict with created contact details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not email:
            return {"error": "email is required"}

        payload: dict[str, Any] = {"email": email}
        if name:
            payload["name"] = name
        if phone:
            payload["phone"] = phone
        if company_id is not None:
            payload["company_id"] = company_id

        url = f"{_base_url(domain)}/contacts"
        data = _request("post", url, api_key, json=payload)
        if "error" in data:
            return data

        return _extract_contact(data)

    @mcp.tool()
    def freshdesk_update_contact(
        contact_id: int,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Update a Freshdesk contact.

        Args:
            contact_id: Freshdesk contact ID (required)
            name: Optional new name
            email: Optional new email
            phone: Optional new phone
            company_id: Optional company ID (set to -1 to clear)

        Returns:
            Dict with updated contact details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not contact_id:
            return {"error": "contact_id is required"}

        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if email is not None:
            payload["email"] = email
        if phone is not None:
            payload["phone"] = phone
        if company_id is not None:
            payload["company_id"] = company_id
        if not payload:
            return {"error": "At least one field (name, email, phone, company_id) is required"}

        url = f"{_base_url(domain)}/contacts/{contact_id}"
        data = _request("put", url, api_key, json=payload)
        if "error" in data:
            return data
        return _extract_contact(data)

    @mcp.tool()
    def freshdesk_list_agents(
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        """
        List agents in Freshdesk.

        Args:
            page: Page number (1-based, default 1)
            per_page: Agents per page (1-100, default 30)

        Returns:
            Dict with agents list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()

        url = f"{_base_url(domain)}/agents"
        per_page_clamped = max(1, min(per_page, 100))
        params = {"page": max(1, page), "per_page": per_page_clamped}

        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        agents = [_extract_agent(a) for a in data]
        return {"agents": agents, "count": len(agents)}

    @mcp.tool()
    def freshdesk_get_agent(
        agent_id: int,
    ) -> dict[str, Any]:
        """
        Get a single Freshdesk agent by ID.

        Args:
            agent_id: Freshdesk agent ID (required)

        Returns:
            Dict with agent details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not agent_id:
            return {"error": "agent_id is required"}

        url = f"{_base_url(domain)}/agents/{agent_id}"
        data = _request("get", url, api_key)
        if "error" in data:
            return data
        return _extract_agent(data)

    @mcp.tool()
    def freshdesk_list_groups(
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        """
        List groups in Freshdesk.

        Args:
            page: Page number (1-based, default 1)
            per_page: Groups per page (1-100, default 30)

        Returns:
            Dict with groups list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()

        url = f"{_base_url(domain)}/groups"
        per_page_clamped = max(1, min(per_page, 100))
        params = {"page": max(1, page), "per_page": per_page_clamped}
        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        groups = [_extract_group(g) for g in data]
        return {"groups": groups, "count": len(groups)}

    @mcp.tool()
    def freshdesk_get_group(
        group_id: int,
    ) -> dict[str, Any]:
        """
        Get a single Freshdesk group by ID.

        Args:
            group_id: Freshdesk group ID (required)

        Returns:
            Dict with group details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not group_id:
            return {"error": "group_id is required"}

        url = f"{_base_url(domain)}/groups/{group_id}"
        data = _request("get", url, api_key)
        if "error" in data:
            return data
        return _extract_group(data)

    @mcp.tool()
    def freshdesk_list_companies(
        page: int = 1,
        per_page: int = 30,
        updated_since: str | None = None,
    ) -> dict[str, Any]:
        """
        List companies in Freshdesk.

        Args:
            page: Page number (default 1)
            per_page: Companies per page (1-100, default 30)
            updated_since: Optional ISO8601 timestamp to list companies updated since

        Returns:
            Dict with companies list and count.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()

        url = f"{_base_url(domain)}/companies"
        per_page_clamped = max(1, min(per_page, 100))
        params: dict[str, Any] = {"page": max(1, page), "per_page": per_page_clamped}
        if updated_since:
            params["updated_since"] = updated_since

        data = _request("get", url, api_key, params=params)
        if "error" in data:
            return data

        companies = [_extract_company(c) for c in data]
        return {"companies": companies, "count": len(companies)}

    @mcp.tool()
    def freshdesk_get_company(
        company_id: int,
    ) -> dict[str, Any]:
        """
        Get a single Freshdesk company by ID.

        Args:
            company_id: Freshdesk company ID (required)

        Returns:
            Dict with company details.
        """
        api_key = _get_api_key(credentials)
        if not api_key:
            return _auth_error()
        domain = _get_domain(credentials)
        if not domain:
            return _domain_error()
        if not company_id:
            return {"error": "company_id is required"}

        url = f"{_base_url(domain)}/companies/{company_id}"
        data = _request("get", url, api_key)
        if "error" in data:
            return data
        return _extract_company(data)
