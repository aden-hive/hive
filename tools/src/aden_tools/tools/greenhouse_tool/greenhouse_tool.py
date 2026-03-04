"""
Greenhouse Tool - ATS & recruiting workflow via Harvest API.

Supports:
- Greenhouse Harvest API v1 (Basic auth with API token)
- Jobs, candidates, and applications management

API Reference: https://developers.greenhouse.io/harvest.html
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_BASE = "https://harvest.greenhouse.io/v1"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> str | None:
    """Return the Greenhouse API token."""
    if credentials is not None:
        return credentials.get("greenhouse_token")
    return os.getenv("GREENHOUSE_API_TOKEN")


def _auth_header(token: str) -> str:
    encoded = base64.b64encode(f"{token}:".encode()).decode()
    return f"Basic {encoded}"


def _get(path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list:
    """Make an authenticated GET to the Greenhouse Harvest API."""
    try:
        resp = httpx.get(
            f"{API_BASE}{path}",
            headers={"Authorization": _auth_header(token)},
            params=params or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Greenhouse API token."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Your API key may lack the required permissions."}
        if resp.status_code == 404:
            return {"error": "Resource not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code != 200:
            return {"error": f"Greenhouse API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Greenhouse timed out"}
    except Exception as e:
        return {"error": f"Greenhouse request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "GREENHOUSE_API_TOKEN not set",
        "help": (
            "Get your API key from Greenhouse: Configure > Dev Center > API Credential Management"
        ),
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Greenhouse tools with the MCP server."""

    @mcp.tool()
    def greenhouse_list_jobs(
        status: str = "",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List jobs in Greenhouse.

        Args:
            status: Filter by status: open, closed, draft (optional)
            per_page: Results per page (1-500, default 50)
            page: Page number (default 1)

        Returns:
            Dict with jobs list (id, name, status, departments, offices)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "per_page": max(1, min(per_page, 500)),
            "page": max(1, page),
        }
        if status:
            params["status"] = status

        data = _get("/jobs", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        jobs = []
        for j in data if isinstance(data, list) else []:
            jobs.append(
                {
                    "id": j.get("id"),
                    "name": j.get("name", ""),
                    "status": j.get("status", ""),
                    "departments": [d.get("name", "") for d in j.get("departments", [])],
                    "offices": [o.get("name", "") for o in j.get("offices", [])],
                    "created_at": j.get("created_at", ""),
                    "updated_at": j.get("updated_at", ""),
                }
            )
        return {"jobs": jobs, "count": len(jobs)}

    @mcp.tool()
    def greenhouse_get_job(job_id: int) -> dict[str, Any]:
        """
        Get details about a specific job.

        Args:
            job_id: Greenhouse job ID (required)

        Returns:
            Dict with job details including hiring team and openings
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not job_id:
            return {"error": "job_id is required"}

        data = _get(f"/jobs/{job_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        return {
            "id": data.get("id"),
            "name": data.get("name", ""),
            "status": data.get("status", ""),
            "confidential": data.get("confidential", False),
            "departments": [d.get("name", "") for d in data.get("departments", [])],
            "offices": [o.get("name", "") for o in data.get("offices", [])],
            "openings": [
                {"id": o.get("id"), "status": o.get("status", "")} for o in data.get("openings", [])
            ],
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "notes": (data.get("notes") or "")[:500],
        }

    @mcp.tool()
    def greenhouse_list_candidates(
        job_id: int = 0,
        email: str = "",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List candidates in Greenhouse.

        Args:
            job_id: Filter by job ID (optional, 0 = all)
            email: Filter by email address (optional)
            per_page: Results per page (1-500, default 50)
            page: Page number (default 1)

        Returns:
            Dict with candidates list (id, name, company, title, tags)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "per_page": max(1, min(per_page, 500)),
            "page": max(1, page),
        }
        if job_id:
            params["job_id"] = job_id
        if email:
            params["email"] = email

        data = _get("/candidates", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        candidates = []
        for c in data if isinstance(data, list) else []:
            candidates.append(
                {
                    "id": c.get("id"),
                    "first_name": c.get("first_name", ""),
                    "last_name": c.get("last_name", ""),
                    "company": c.get("company", ""),
                    "title": c.get("title", ""),
                    "tags": c.get("tags", []),
                    "application_ids": c.get("application_ids", []),
                    "created_at": c.get("created_at", ""),
                }
            )
        return {"candidates": candidates, "count": len(candidates)}

    @mcp.tool()
    def greenhouse_get_candidate(candidate_id: int) -> dict[str, Any]:
        """
        Get details about a specific candidate.

        Args:
            candidate_id: Greenhouse candidate ID (required)

        Returns:
            Dict with candidate details including applications and contact info
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not candidate_id:
            return {"error": "candidate_id is required"}

        data = _get(f"/candidates/{candidate_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        emails = [e.get("value", "") for e in data.get("email_addresses", [])]
        phones = [p.get("value", "") for p in data.get("phone_numbers", [])]

        return {
            "id": data.get("id"),
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "company": data.get("company", ""),
            "title": data.get("title", ""),
            "emails": emails,
            "phones": phones,
            "tags": data.get("tags", []),
            "application_ids": data.get("application_ids", []),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }

    @mcp.tool()
    def greenhouse_list_applications(
        job_id: int = 0,
        status: str = "",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List applications in Greenhouse.

        Args:
            job_id: Filter by job ID (optional, 0 = all)
            status: Filter by status: active, converted, hired, rejected (optional)
            per_page: Results per page (1-500, default 50)
            page: Page number (default 1)

        Returns:
            Dict with applications list (id, candidate_id, status, current_stage)
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "per_page": max(1, min(per_page, 500)),
            "page": max(1, page),
        }
        if job_id:
            params["job_id"] = job_id
        if status:
            params["status"] = status

        data = _get("/applications", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        apps = []
        for a in data if isinstance(data, list) else []:
            stage = a.get("current_stage") or {}
            jobs = [j.get("name", "") for j in a.get("jobs", [])]
            apps.append(
                {
                    "id": a.get("id"),
                    "candidate_id": a.get("candidate_id"),
                    "status": a.get("status", ""),
                    "current_stage": stage.get("name", ""),
                    "jobs": jobs,
                    "applied_at": a.get("applied_at", ""),
                    "last_activity_at": a.get("last_activity_at", ""),
                }
            )
        return {"applications": apps, "count": len(apps)}

    @mcp.tool()
    def greenhouse_get_application(application_id: int) -> dict[str, Any]:
        """
        Get details about a specific application.

        Args:
            application_id: Greenhouse application ID (required)

        Returns:
            Dict with application details including stage, source, and answers
        """
        token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not application_id:
            return {"error": "application_id is required"}

        data = _get(f"/applications/{application_id}", token)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        stage = data.get("current_stage") or {}
        source = data.get("source") or {}
        jobs = [j.get("name", "") for j in data.get("jobs", [])]
        answers = [
            {"question": a.get("question", ""), "answer": a.get("answer", "")}
            for a in data.get("answers", [])
        ]

        return {
            "id": data.get("id"),
            "candidate_id": data.get("candidate_id"),
            "status": data.get("status", ""),
            "current_stage": stage.get("name", ""),
            "source": source.get("public_name", ""),
            "jobs": jobs,
            "answers": answers,
            "applied_at": data.get("applied_at", ""),
            "rejected_at": data.get("rejected_at"),
            "last_activity_at": data.get("last_activity_at", ""),
        }
