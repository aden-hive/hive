"""
TickTick Tool - Manage tasks and projects via TickTick Open API v1.

Supports:
- Task CRUD (create, list, update, complete, delete)
- Project management (list, create)
- Tag listing

API Reference: https://developer.ticktick.com/docs
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

TICKTICK_API_BASE = "https://api.ticktick.com/open/v1"
DEFAULT_TIMEOUT = 30.0


class _TickTickClient:
    """Internal client wrapping TickTick Open API v1 calls."""

    def __init__(self, access_token: str):
        self._access_token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired TickTick access token"}
        if response.status_code == 403:
            return {"error": "Access forbidden. Check token permissions."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"TickTick API error (HTTP {response.status_code}): {detail}"}
        # 2xx with empty body (e.g. 204 on delete)
        if not response.content:
            return {"success": True}
        return response.json()

    def create_task(
        self,
        title: str,
        project_id: str | None = None,
        content: str | None = None,
        due_date: str | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Create a new task.

        Args:
            title: Task title.
            project_id: Optional project (list) ID to add the task to.
            content: Optional task description / notes.
            due_date: Optional due date in ISO 8601 format.
            priority: Task priority (0=none, 1=low, 3=medium, 5=high).

        Returns:
            Created task data or error dict.
        """
        body: dict[str, Any] = {"title": title, "priority": priority}
        if project_id is not None:
            body["projectId"] = project_id
        if content is not None:
            body["content"] = content
        if due_date is not None:
            body["dueDate"] = due_date

        response = httpx.post(
            f"{TICKTICK_API_BASE}/task",
            headers=self._headers,
            json=body,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def list_tasks(self, project_id: str) -> dict[str, Any]:
        """List tasks for a given project.

        The TickTick Open API v1 ``/project/{project_id}/data`` endpoint
        returns a project object that contains a ``tasks`` list.

        Args:
            project_id: The project (list) ID.

        Returns:
            Dict with ``tasks`` list or error dict.
        """
        response = httpx.get(
            f"{TICKTICK_API_BASE}/project/{project_id}/data",
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        result = self._handle_response(response)
        if "error" in result:
            return result
        # Extract the tasks list from the project data envelope
        tasks = result.get("tasks", [])
        return {"tasks": tasks}

    def update_task(
        self,
        task_id: str,
        project_id: str,
        title: str | None = None,
        content: str | None = None,
        status: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing task.

        Args:
            task_id: The task ID.
            project_id: The project (list) ID the task belongs to.
            title: New title (optional).
            content: New description (optional).
            status: New status value (optional).

        Returns:
            Updated task data or error dict.
        """
        body: dict[str, Any] = {"projectId": project_id}
        if title is not None:
            body["title"] = title
        if content is not None:
            body["content"] = content
        if status is not None:
            body["status"] = status

        response = httpx.post(
            f"{TICKTICK_API_BASE}/task/{task_id}",
            headers=self._headers,
            json=body,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def complete_task(self, task_id: str, project_id: str) -> dict[str, Any]:
        """Mark a task as complete.

        Args:
            task_id: The task ID.
            project_id: The project (list) ID the task belongs to.

        Returns:
            Success indicator or error dict.
        """
        response = httpx.post(
            f"{TICKTICK_API_BASE}/project/{project_id}/task/{task_id}/complete",
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def delete_task(self, task_id: str, project_id: str) -> dict[str, Any]:
        """Delete a task.

        Args:
            task_id: The task ID.
            project_id: The project (list) ID the task belongs to.

        Returns:
            Success indicator or error dict.
        """
        response = httpx.delete(
            f"{TICKTICK_API_BASE}/project/{project_id}/task/{task_id}",
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def list_projects(self) -> dict[str, Any]:
        """List all projects (task lists).

        Returns:
            Dict with ``projects`` list or error dict.
        """
        response = httpx.get(
            f"{TICKTICK_API_BASE}/project",
            headers=self._headers,
            timeout=DEFAULT_TIMEOUT,
        )
        result = self._handle_response(response)
        if "error" in result:
            return result
        # The endpoint returns a JSON array of projects
        if isinstance(result, list):
            return {"projects": result}
        return result

    def create_project(self, name: str) -> dict[str, Any]:
        """Create a new project (task list).

        Args:
            name: Project name.

        Returns:
            Created project data or error dict.
        """
        body: dict[str, Any] = {"name": name}
        response = httpx.post(
            f"{TICKTICK_API_BASE}/project",
            headers=self._headers,
            json=body,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register TickTick tools with the MCP server."""

    def _get_token() -> str | None:
        """Get TickTick access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("ticktick")
            if token is not None and not isinstance(token, str):
                return None
            return token
        return os.getenv("TICKTICK_ACCESS_TOKEN")

    def _get_client() -> _TickTickClient | dict[str, str]:
        """Get a TickTick client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "TickTick credentials not configured",
                "help": (
                    "Set TICKTICK_ACCESS_TOKEN environment variable "
                    "or configure via credential store"
                ),
            }
        return _TickTickClient(token)

    # --- Tasks ---

    @mcp.tool()
    def ticktick_create_task(
        title: str,
        project_id: str | None = None,
        content: str | None = None,
        due_date: str | None = None,
        priority: int = 0,
    ) -> dict:
        """
        Create a new task in TickTick.

        Use this when you need to:
        - Add a new task or to-do item
        - Assign a task to a specific project
        - Set a due date or priority

        Args:
            title: Task title (required)
            project_id: Project (list) ID to add the task to
            content: Task description or notes
            due_date: Due date in ISO 8601 format (e.g. '2024-12-31T23:59:00+0000')
            priority: Priority level (0=none, 1=low, 3=medium, 5=high)

        Returns:
            Dict with created task details or error
        """
        if not title or not title.strip():
            return {"error": "Task title is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.create_task(
                title=title,
                project_id=project_id,
                content=content,
                due_date=due_date,
                priority=priority,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ticktick_list_tasks(project_id: str) -> dict:
        """
        List tasks in a TickTick project.

        Use this when you need to:
        - View all tasks in a specific project/list
        - Get task IDs for updating or completing tasks

        Args:
            project_id: The project (list) ID to retrieve tasks from

        Returns:
            Dict with list of tasks or error
        """
        if not project_id or not project_id.strip():
            return {"error": "Project ID is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.list_tasks(project_id=project_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ticktick_update_task(
        task_id: str,
        project_id: str,
        title: str | None = None,
        content: str | None = None,
        status: int | None = None,
    ) -> dict:
        """
        Update an existing task in TickTick.

        Use this when you need to:
        - Change a task's title or description
        - Update a task's status

        Args:
            task_id: The task ID to update
            project_id: The project (list) ID the task belongs to
            title: New task title
            content: New task description or notes
            status: New status value

        Returns:
            Dict with updated task details or error
        """
        if not task_id or not task_id.strip():
            return {"error": "Task ID is required"}
        if not project_id or not project_id.strip():
            return {"error": "Project ID is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.update_task(
                task_id=task_id,
                project_id=project_id,
                title=title,
                content=content,
                status=status,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ticktick_complete_task(task_id: str, project_id: str) -> dict:
        """
        Mark a task as complete in TickTick.

        Use this when you need to:
        - Complete a task or to-do item
        - Mark work as done

        Args:
            task_id: The task ID to complete
            project_id: The project (list) ID the task belongs to

        Returns:
            Dict with success indicator or error
        """
        if not task_id or not task_id.strip():
            return {"error": "Task ID is required"}
        if not project_id or not project_id.strip():
            return {"error": "Project ID is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.complete_task(task_id=task_id, project_id=project_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ticktick_delete_task(task_id: str, project_id: str) -> dict:
        """
        Delete a task from TickTick.

        Use this when you need to:
        - Remove a task permanently
        - Clean up completed or unwanted tasks

        Args:
            task_id: The task ID to delete
            project_id: The project (list) ID the task belongs to

        Returns:
            Dict with success indicator or error
        """
        if not task_id or not task_id.strip():
            return {"error": "Task ID is required"}
        if not project_id or not project_id.strip():
            return {"error": "Project ID is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.delete_task(task_id=task_id, project_id=project_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Projects ---

    @mcp.tool()
    def ticktick_list_projects() -> dict:
        """
        List all projects (task lists) in TickTick.

        Use this when you need to:
        - Get an overview of all task lists
        - Find project IDs for creating or listing tasks

        Returns:
            Dict with list of projects or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.list_projects()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ticktick_create_project(name: str) -> dict:
        """
        Create a new project (task list) in TickTick.

        Use this when you need to:
        - Create a new task list or category
        - Organize tasks into a new project

        Args:
            name: Project name

        Returns:
            Dict with created project details or error
        """
        if not name or not name.strip():
            return {"error": "Project name is required"}

        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.create_project(name=name)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Tags ---

    @mcp.tool()
    def ticktick_list_tags() -> dict:
        """
        List tags in TickTick.

        Note: The TickTick Open API v1 does not provide a dedicated tags
        endpoint. This tool is not supported in the current API version.

        Returns:
            Dict with error indicating lack of API support
        """
        return {"error": "Not implemented in TickTick Open API v1"}
