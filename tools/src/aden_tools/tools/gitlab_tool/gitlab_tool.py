"""
GitLab Tool - Projects, issues, and merge requests via REST API v4.

Supports:
- GitLab.com and self-hosted instances
- Personal access token auth (PRIVATE-TOKEN header)
- Projects, issues, merge requests

API Reference: https://docs.gitlab.com/api/rest/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_URL = "https://gitlab.com"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (base_url, token)."""
    if credentials is not None:
        url = credentials.get("gitlab_url") or DEFAULT_URL
        token = credentials.get("gitlab_token")
        return url, token
    url = os.getenv("GITLAB_URL", DEFAULT_URL)
    token = os.getenv("GITLAB_TOKEN")
    return url, token


def _get(
    base_url: str, path: str, token: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | list:
    """Make an authenticated GET to the GitLab API."""
    try:
        resp = httpx.get(
            f"{base_url}/api/v4{path}",
            headers={"PRIVATE-TOKEN": token},
            params=params or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your GitLab token."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Insufficient permissions."}
        if resp.status_code == 404:
            return {"error": "Not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201):
            return {"error": f"GitLab API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to GitLab timed out"}
    except Exception as e:
        return {"error": f"GitLab request failed: {e!s}"}


def _post(
    base_url: str, path: str, token: str, json: dict[str, Any] | None = None
) -> dict[str, Any] | list:
    """Make an authenticated POST to the GitLab API."""
    try:
        resp = httpx.post(
            f"{base_url}/api/v4{path}",
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
            json=json or {},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your GitLab token."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Insufficient permissions."}
        if resp.status_code not in (200, 201):
            return {"error": f"GitLab API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to GitLab timed out"}
    except Exception as e:
        return {"error": f"GitLab request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "GITLAB_TOKEN not set",
        "help": "Create a personal access token at https://gitlab.com/-/user_settings/personal_access_tokens",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register GitLab tools with the MCP server."""

    @mcp.tool()
    def gitlab_list_projects(
        search: str = "",
        owned: bool = False,
        membership: bool = True,
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List GitLab projects.

        Args:
            search: Search by project name (optional)
            owned: Only projects owned by you (default False)
            membership: Only projects you're a member of (default True)
            per_page: Results per page (1-100, default 20)
            page: Page number (default 1)

        Returns:
            Dict with projects list (id, name, path, visibility, web_url)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()

        params: dict[str, Any] = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
            "membership": str(membership).lower(),
        }
        if search:
            params["search"] = search
        if owned:
            params["owned"] = "true"

        data = _get(base_url, "/projects", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        projects = []
        for p in data if isinstance(data, list) else []:
            projects.append(
                {
                    "id": p.get("id"),
                    "name": p.get("name", ""),
                    "path_with_namespace": p.get("path_with_namespace", ""),
                    "description": (p.get("description") or "")[:200],
                    "visibility": p.get("visibility", ""),
                    "default_branch": p.get("default_branch", ""),
                    "web_url": p.get("web_url", ""),
                    "star_count": p.get("star_count", 0),
                    "last_activity_at": p.get("last_activity_at", ""),
                }
            )
        return {"projects": projects, "count": len(projects)}

    @mcp.tool()
    def gitlab_get_project(project_id: str) -> dict[str, Any]:
        """
        Get details about a GitLab project.

        Args:
            project_id: Project ID (numeric) or URL-encoded path e.g. "group%2Fproject" (required)

        Returns:
            Dict with project details (name, description, stats, URLs)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        data = _get(base_url, f"/projects/{project_id}", token, {"statistics": "true"})
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        stats = data.get("statistics") or {}
        return {
            "id": data.get("id"),
            "name": data.get("name", ""),
            "path_with_namespace": data.get("path_with_namespace", ""),
            "description": (data.get("description") or "")[:500],
            "visibility": data.get("visibility", ""),
            "default_branch": data.get("default_branch", ""),
            "web_url": data.get("web_url", ""),
            "star_count": data.get("star_count", 0),
            "forks_count": data.get("forks_count", 0),
            "open_issues_count": data.get("open_issues_count", 0),
            "commit_count": stats.get("commit_count", 0),
            "created_at": data.get("created_at", ""),
            "last_activity_at": data.get("last_activity_at", ""),
        }

    @mcp.tool()
    def gitlab_list_issues(
        project_id: str,
        state: str = "opened",
        labels: str = "",
        search: str = "",
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List issues in a GitLab project.

        Args:
            project_id: Project ID or URL-encoded path (required)
            state: Filter: opened, closed, all (default opened)
            labels: Comma-separated label names (optional)
            search: Search in title and description (optional)
            per_page: Results per page (1-100, default 20)
            page: Page number (default 1)

        Returns:
            Dict with issues list (iid, title, state, labels, assignees)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        params: dict[str, Any] = {
            "state": state,
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }
        if labels:
            params["labels"] = labels
        if search:
            params["search"] = search

        data = _get(base_url, f"/projects/{project_id}/issues", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        issues = []
        for i in data if isinstance(data, list) else []:
            assignees = [a.get("username", "") for a in i.get("assignees", [])]
            issues.append(
                {
                    "iid": i.get("iid"),
                    "title": i.get("title", ""),
                    "state": i.get("state", ""),
                    "labels": i.get("labels", []),
                    "assignees": assignees,
                    "author": (i.get("author") or {}).get("username", ""),
                    "created_at": i.get("created_at", ""),
                    "updated_at": i.get("updated_at", ""),
                    "web_url": i.get("web_url", ""),
                }
            )
        return {"issues": issues, "count": len(issues)}

    @mcp.tool()
    def gitlab_get_issue(project_id: str, issue_iid: int) -> dict[str, Any]:
        """
        Get details about a specific issue.

        Args:
            project_id: Project ID or URL-encoded path (required)
            issue_iid: Issue internal ID within the project (required)

        Returns:
            Dict with issue details (title, description, state, labels, etc.)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not project_id or not issue_iid:
            return {"error": "project_id and issue_iid are required"}

        data = _get(base_url, f"/projects/{project_id}/issues/{issue_iid}", token)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        assignees = [a.get("username", "") for a in data.get("assignees", [])]
        milestone = data.get("milestone") or {}

        return {
            "iid": data.get("iid"),
            "title": data.get("title", ""),
            "description": (data.get("description") or "")[:1000],
            "state": data.get("state", ""),
            "labels": data.get("labels", []),
            "assignees": assignees,
            "author": (data.get("author") or {}).get("username", ""),
            "milestone": milestone.get("title", ""),
            "due_date": data.get("due_date"),
            "web_url": data.get("web_url", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "closed_at": data.get("closed_at"),
        }

    @mcp.tool()
    def gitlab_create_issue(
        project_id: str,
        title: str,
        description: str = "",
        labels: str = "",
        assignee_ids: str = "",
    ) -> dict[str, Any]:
        """
        Create a new issue in a GitLab project.

        Args:
            project_id: Project ID or URL-encoded path (required)
            title: Issue title (required)
            description: Issue body text (optional)
            labels: Comma-separated label names (optional)
            assignee_ids: Comma-separated user IDs to assign (optional)

        Returns:
            Dict with created issue (iid, title, web_url)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not project_id or not title:
            return {"error": "project_id and title are required"}

        body: dict[str, Any] = {"title": title}
        if description:
            body["description"] = description
        if labels:
            body["labels"] = labels
        if assignee_ids:
            body["assignee_ids"] = [int(x.strip()) for x in assignee_ids.split(",") if x.strip()]

        data = _post(base_url, f"/projects/{project_id}/issues", token, json=body)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response format"}

        return {
            "iid": data.get("iid"),
            "title": data.get("title", ""),
            "web_url": data.get("web_url", ""),
            "status": "created",
        }

    @mcp.tool()
    def gitlab_list_merge_requests(
        project_id: str,
        state: str = "opened",
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        List merge requests in a GitLab project.

        Args:
            project_id: Project ID or URL-encoded path (required)
            state: Filter: opened, closed, merged, locked, all (default opened)
            per_page: Results per page (1-100, default 20)
            page: Page number (default 1)

        Returns:
            Dict with merge requests list (iid, title, state, source/target branch)
        """
        base_url, token = _get_credentials(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        params: dict[str, Any] = {
            "state": state,
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }

        data = _get(base_url, f"/projects/{project_id}/merge_requests", token, params)
        if isinstance(data, dict) and "error" in data:
            return data

        mrs = []
        for mr in data if isinstance(data, list) else []:
            mrs.append(
                {
                    "iid": mr.get("iid"),
                    "title": mr.get("title", ""),
                    "state": mr.get("state", ""),
                    "source_branch": mr.get("source_branch", ""),
                    "target_branch": mr.get("target_branch", ""),
                    "author": (mr.get("author") or {}).get("username", ""),
                    "web_url": mr.get("web_url", ""),
                    "created_at": mr.get("created_at", ""),
                    "updated_at": mr.get("updated_at", ""),
                }
            )
        return {"merge_requests": mrs, "count": len(mrs)}
