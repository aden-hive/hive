"""
Asana Tool - Task and project management.

Supports:
- Asana personal access token (ASANA_ACCESS_TOKEN)
- Tasks, Projects, Workspaces, Sections, Tags

API Reference: https://developers.asana.com/docs
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

ASANA_API = "https://app.asana.com/api/1.0"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("asana")
    return os.getenv("ASANA_ACCESS_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{ASANA_API}/{endpoint}", headers=_headers(token), params=params, timeout=30.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ASANA_ACCESS_TOKEN."}
        if resp.status_code == 403:
            return {"error": f"Forbidden: {resp.text[:300]}"}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code != 200:
            return {"error": f"Asana API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Asana timed out"}
    except Exception as e:
        return {"error": f"Asana request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{ASANA_API}/{endpoint}",
            headers=_headers(token),
            json={"data": body or {}},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your ASANA_ACCESS_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Asana API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Asana timed out"}
    except Exception as e:
        return {"error": f"Asana request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "ASANA_ACCESS_TOKEN not set",
        "help": "Create a PAT at https://app.asana.com/0/my-apps",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Asana tools with the MCP server."""

    @mcp.tool()
    def asana_list_workspaces() -> dict[str, Any]:
        """
        List all workspaces accessible to the authenticated user.

        Returns:
            Dict with workspaces list (gid, name)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("workspaces", token)
        if "error" in data:
            return data

        workspaces = []
        for w in data.get("data", []):
            workspaces.append({"gid": w.get("gid", ""), "name": w.get("name", "")})
        return {"workspaces": workspaces}

    @mcp.tool()
    def asana_list_projects(
        workspace_gid: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        List projects in an Asana workspace.

        Args:
            workspace_gid: Workspace GID
            limit: Number of results (1-100, default 50)

        Returns:
            Dict with projects list (gid, name, color, archived)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not workspace_gid:
            return {"error": "workspace_gid is required"}

        params = {
            "workspace": workspace_gid,
            "limit": max(1, min(limit, 100)),
            "opt_fields": "name,color,archived,created_at",
        }
        data = _get("projects", token, params)
        if "error" in data:
            return data

        projects = []
        for p in data.get("data", []):
            projects.append(
                {
                    "gid": p.get("gid", ""),
                    "name": p.get("name", ""),
                    "color": p.get("color", ""),
                    "archived": p.get("archived", False),
                }
            )
        return {"projects": projects}

    @mcp.tool()
    def asana_list_tasks(
        project_gid: str = "",
        assignee: str = "me",
        workspace_gid: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        List tasks from Asana, filtered by project or assignee.

        Args:
            project_gid: Project GID to filter by (optional)
            assignee: Assignee: "me" or user GID (used with workspace_gid)
            workspace_gid: Workspace GID (required when filtering by assignee without project)
            limit: Number of results (1-100, default 50)

        Returns:
            Dict with tasks list (gid, name, completed, due_on, assignee_name)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not project_gid and not workspace_gid:
            return {"error": "Either project_gid or workspace_gid is required"}

        params: dict[str, Any] = {
            "limit": max(1, min(limit, 100)),
            "opt_fields": "name,completed,due_on,assignee.name",
        }
        if project_gid:
            params["project"] = project_gid
        else:
            params["workspace"] = workspace_gid
            params["assignee"] = assignee

        data = _get("tasks", token, params)
        if "error" in data:
            return data

        tasks = []
        for t in data.get("data", []):
            assignee_obj = t.get("assignee") or {}
            tasks.append(
                {
                    "gid": t.get("gid", ""),
                    "name": t.get("name", ""),
                    "completed": t.get("completed", False),
                    "due_on": t.get("due_on", ""),
                    "assignee_name": assignee_obj.get("name", ""),
                }
            )
        return {"tasks": tasks, "count": len(tasks)}

    @mcp.tool()
    def asana_get_task(task_gid: str) -> dict[str, Any]:
        """
        Get details of a specific Asana task.

        Args:
            task_gid: Task GID

        Returns:
            Dict with task details: name, notes, completed, due_on, assignee, projects, tags
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not task_gid:
            return {"error": "task_gid is required"}

        params = {
            "opt_fields": (
                "name,notes,completed,due_on,assignee.name,"
                "projects.name,tags.name,created_at,modified_at"
            )
        }
        data = _get(f"tasks/{task_gid}", token, params)
        if "error" in data:
            return data

        t = data.get("data", {})
        assignee_obj = t.get("assignee") or {}
        return {
            "gid": t.get("gid", ""),
            "name": t.get("name", ""),
            "notes": (t.get("notes", "") or "")[:500],
            "completed": t.get("completed", False),
            "due_on": t.get("due_on", ""),
            "assignee_name": assignee_obj.get("name", ""),
            "projects": [p.get("name", "") for p in t.get("projects", [])],
            "tags": [tag.get("name", "") for tag in t.get("tags", [])],
            "created_at": t.get("created_at", ""),
            "modified_at": t.get("modified_at", ""),
        }

    @mcp.tool()
    def asana_create_task(
        workspace_gid: str,
        name: str,
        notes: str = "",
        project_gid: str = "",
        assignee: str = "",
        due_on: str = "",
    ) -> dict[str, Any]:
        """
        Create a new task in Asana.

        Args:
            workspace_gid: Workspace GID (required)
            name: Task name (required)
            notes: Task description/notes (optional)
            project_gid: Add to this project (optional)
            assignee: Assignee GID or "me" (optional)
            due_on: Due date YYYY-MM-DD (optional)

        Returns:
            Dict with created task gid, name, and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not workspace_gid or not name:
            return {"error": "workspace_gid and name are required"}

        body: dict[str, Any] = {"workspace": workspace_gid, "name": name}
        if notes:
            body["notes"] = notes
        if project_gid:
            body["projects"] = [project_gid]
        if assignee:
            body["assignee"] = assignee
        if due_on:
            body["due_on"] = due_on

        data = _post("tasks", token, body)
        if "error" in data:
            return data

        t = data.get("data", {})
        return {"gid": t.get("gid", ""), "name": t.get("name", ""), "status": "created"}

    @mcp.tool()
    def asana_search_tasks(
        workspace_gid: str,
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Search tasks in an Asana workspace.

        Args:
            workspace_gid: Workspace GID
            query: Search text
            limit: Number of results (1-100, default 20)

        Returns:
            Dict with matching tasks (gid, name, completed)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not workspace_gid or not query:
            return {"error": "workspace_gid and query are required"}

        params = {
            "text": query,
            "limit": max(1, min(limit, 100)),
            "opt_fields": "name,completed,due_on",
        }
        data = _get(f"workspaces/{workspace_gid}/tasks/search", token, params)
        if "error" in data:
            return data

        tasks = []
        for t in data.get("data", []):
            tasks.append(
                {
                    "gid": t.get("gid", ""),
                    "name": t.get("name", ""),
                    "completed": t.get("completed", False),
                    "due_on": t.get("due_on", ""),
                }
            )
        return {"query": query, "tasks": tasks}
