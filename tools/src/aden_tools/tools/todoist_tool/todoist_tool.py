"""
Todoist Tool - Tasks and projects via Todoist REST API v2.

Supports:
- Personal API token (Bearer auth)

API Reference: https://developer.todoist.com/rest/v2/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_BASE = "https://api.todoist.com/rest/v2"


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Todoist tools with the MCP server."""

    def _get_credentials() -> str | None:
        """Return the Todoist API token."""
        if credentials is not None:
            return credentials.get("todoist_token")
        return os.getenv("TODOIST_API_TOKEN")

    def _headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _error_from_response(response: httpx.Response) -> dict[str, Any]:
        """Map Todoist HTTP errors to a dict with 'error'."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Todoist API token"}
        if response.status_code == 403:
            return {"error": "Todoist API returned forbidden for this token"}
        if response.status_code == 404:
            return {"error": "Todoist resource not found"}
        if response.status_code == 429:
            return {"error": "Todoist rate limit exceeded. Try again later."}
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                return {"error": f"Todoist API error: {data.get('error')}"}
        except Exception:
            pass
        return {
            "error": f"Todoist API error {response.status_code}: {response.text[:500]}",
        }

    def _request(
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a sync HTTP request to the Todoist REST API."""
        url = f"{API_BASE}{path}"
        try:
            fn = getattr(httpx, method.lower())
            kwargs: dict[str, Any] = {"headers": _headers(token), "timeout": 30.0}
            if params is not None:
                kwargs["params"] = params
            if json_body is not None:
                kwargs["json"] = json_body
            response = fn(url, **kwargs)

            if response.status_code == 204:
                return {"_no_content": True}

            if response.status_code not in (200, 201):
                return _error_from_response(response)

            try:
                return response.json()  # type: ignore[no-any-return]
            except Exception:
                return {"error": "Todoist returned invalid JSON"}
        except httpx.TimeoutException:
            return {"error": "Request to Todoist timed out"}
        except Exception as e:
            return {"error": f"Todoist request failed: {e!s}"}

    def _auth_error() -> dict[str, Any]:
        return {
            "error": "TODOIST_API_TOKEN not set",
            "help": "Create a token at https://todoist.com/app/settings/integrations",
        }

    @mcp.tool()
    def todoist_get_tasks(
        project_id: str = "",
        label_ids: str = "",
        priority: int = 0,
    ) -> dict[str, Any]:
        """
        List active tasks from Todoist.

        Args:
            project_id: Filter by project ID (optional)
            label_ids: Comma-separated label IDs (optional)
            priority: Filter by priority 1–4 (4 = urgent); 0 = no filter (optional)

        Returns:
            Dict with tasks list and count.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()

        if priority != 0 and priority not in (1, 2, 3, 4):
            return {"error": "priority must be 0 (any) or between 1 and 4"}

        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if label_ids:
            params["label_ids"] = label_ids

        data = _request("get", "/tasks", token, params=params or None)
        if "error" in data:
            return data

        if not isinstance(data, list):
            return {"error": "Unexpected response from Todoist when listing tasks"}

        tasks: list[dict[str, Any]] = data
        if priority in (1, 2, 3, 4):
            tasks = [t for t in tasks if t.get("priority") == priority]

        return {"tasks": tasks, "count": len(tasks)}

    @mcp.tool()
    def todoist_create_task(
        content: str,
        due_string: str = "",
        priority: int = 1,
        project_id: str = "",
    ) -> dict[str, Any]:
        """
        Create a new task in Todoist.

        Args:
            content: Task content (required)
            due_string: Natural language due date (optional), e.g. 'tomorrow at 5pm'
            priority: 1 (normal) to 4 (urgent); default 1
            project_id: Target project ID (optional; defaults to Inbox)

        Returns:
            Dict with created task fields from Todoist.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()
        if not content or not content.strip():
            return {"error": "content is required"}
        if priority not in (1, 2, 3, 4):
            return {"error": "priority must be between 1 and 4"}

        body: dict[str, Any] = {
            "content": content.strip(),
            "priority": priority,
        }
        if due_string:
            body["due_string"] = due_string
        if project_id:
            body["project_id"] = project_id

        data = _request("post", "/tasks", token, json_body=body)
        if "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response from Todoist when creating task"}
        return data

    @mcp.tool()
    def todoist_complete_task(task_id: str) -> dict[str, Any]:
        """
        Mark a task as completed (closed) in Todoist.

        Args:
            task_id: Todoist task ID (required)

        Returns:
            Dict with id and status on success.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()
        if not task_id:
            return {"error": "task_id is required"}

        data = _request("post", f"/tasks/{task_id}/close", token)
        if "error" in data:
            return data
        if data.get("_no_content"):
            return {"id": task_id, "status": "completed"}
        return {"id": task_id, "status": "completed"}

    @mcp.tool()
    def todoist_get_projects() -> dict[str, Any]:
        """
        List all projects in Todoist.

        Returns:
            Dict with projects list and count.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()

        data = _request("get", "/projects", token)
        if "error" in data:
            return data
        if not isinstance(data, list):
            return {"error": "Unexpected response from Todoist when listing projects"}
        return {"projects": data, "count": len(data)}

    @mcp.tool()
    def todoist_create_project(
        name: str,
        color: str = "",
    ) -> dict[str, Any]:
        """
        Create a new project in Todoist.

        Args:
            name: Project name (required)
            color: Optional color id (string), e.g. '30' — see Todoist color list

        Returns:
            Dict with created project from Todoist.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()
        if not name or not name.strip():
            return {"error": "name is required"}

        body: dict[str, Any] = {"name": name.strip()}
        if color:
            body["color"] = color

        data = _request("post", "/projects", token, json_body=body)
        if "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": "Unexpected response from Todoist when creating project"}
        return data

    @mcp.tool()
    def todoist_delete_task(task_id: str) -> dict[str, Any]:
        """
        Permanently delete a task from Todoist.

        Args:
            task_id: Todoist task ID (required)

        Returns:
            Dict with id and status on success.
        """
        token = _get_credentials()
        if not token:
            return _auth_error()
        if not task_id:
            return {"error": "task_id is required"}

        data = _request("delete", f"/tasks/{task_id}", token)
        if "error" in data:
            return data
        if data.get("_no_content"):
            return {"id": task_id, "status": "deleted"}
        return {"id": task_id, "status": "deleted"}
