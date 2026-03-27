"""
Todoist Tool - Manage tasks and projects via Todoist API.

Supports:
- API tokens (TODOIST_API_KEY)

API Reference: https://developer.todoist.com/api/v1/
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

TODOIST_API_BASE = "https://api.todoist.com/api/v1"
MAX_RETRIES = 2  # 3 total attempts on 429
MAX_RETRY_WAIT = 60  # cap wait at 60s


class _TodoistClient:
    """Internal client wrapping Todoist API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make HTTP request with retry on 429 rate limit."""
        request_kwargs = {"headers": self._headers, "timeout": 30.0, **kwargs}
        for attempt in range(MAX_RETRIES + 1):
            response = httpx.request(method, url, **request_kwargs)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                wait = min(2**attempt, MAX_RETRY_WAIT)
                time.sleep(wait)
                continue
            return self._handle_response(response)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any] | list[dict[str, Any]]:
        """Handle Todoist API response format."""
        if response.status_code == 204:
            return {"success": True}

        if response.status_code == 429:
            return {
                "error": "Todoist rate limit exceeded. Please try again later.",
                "status_code": 429,
            }

        if response.status_code not in (200, 201):
            try:
                data = response.json()
                message = data if isinstance(data, str) else str(data)
            except Exception:
                message = response.text
            return {"error": f"HTTP {response.status_code}: {message}"}

        try:
            data = response.json()
            # Unified API v1 returns paginated responses with 'results' field
            # For list endpoints, extract the results array
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            return data
        except Exception:
            return {"success": True}

    def list_tasks(
        self,
        project_id: str | None = None,
        label: str | None = None,
        filter_query: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List all active tasks with optional filtering."""
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if label:
            params["label"] = label
        if filter_query:
            params["filter"] = filter_query
        return self._request_with_retry("GET", f"{TODOIST_API_BASE}/tasks", params=params)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get details of a specific task."""
        return self._request_with_retry("GET", f"{TODOIST_API_BASE}/tasks/{task_id}")

    def create_task(
        self,
        content: str,
        description: str | None = None,
        project_id: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int = 1,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new task."""
        body: dict[str, Any] = {"content": content, "priority": priority}
        if description:
            body["description"] = description
        if project_id:
            body["project_id"] = project_id
        if due_string:
            body["due_string"] = due_string
        elif due_date:
            body["due_date"] = due_date
        if labels:
            body["labels"] = labels
        return self._request_with_retry("POST", f"{TODOIST_API_BASE}/tasks", json=body)

    def update_task(
        self,
        task_id: str,
        content: str | None = None,
        description: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing task."""
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if description is not None:
            body["description"] = description
        if due_string is not None:
            body["due_string"] = due_string
        elif due_date is not None:
            body["due_date"] = due_date
        if priority is not None:
            body["priority"] = priority
        if labels is not None:
            body["labels"] = labels
        return self._request_with_retry("POST", f"{TODOIST_API_BASE}/tasks/{task_id}", json=body)

    def complete_task(self, task_id: str) -> dict[str, Any]:
        """Mark a task as complete."""
        return self._request_with_retry("POST", f"{TODOIST_API_BASE}/tasks/{task_id}/close")

    def delete_task(self, task_id: str) -> dict[str, Any]:
        """Delete a task."""
        return self._request_with_retry("DELETE", f"{TODOIST_API_BASE}/tasks/{task_id}")

    def list_projects(self) -> dict[str, Any] | list[dict[str, Any]]:
        """List all projects."""
        return self._request_with_retry("GET", f"{TODOIST_API_BASE}/projects")

    def create_project(
        self,
        name: str,
        color: str | None = None,
        is_favorite: bool = False,
    ) -> dict[str, Any]:
        """Create a new project."""
        body: dict[str, Any] = {"name": name, "is_favorite": is_favorite}
        if color:
            body["color"] = color
        return self._request_with_retry("POST", f"{TODOIST_API_BASE}/projects", json=body)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Todoist tools with the MCP server."""

    def _get_api_key(account: str = "") -> str | None:
        """Get Todoist API key from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("todoist", account)
            api_key = credentials.get("todoist")
            if api_key is not None and not isinstance(api_key, str):
                raise TypeError(
                    f"Expected string from credentials.get('todoist'), got {type(api_key).__name__}"
                )
            return api_key
        return os.getenv("TODOIST_API_KEY")

    def _get_client(account: str = "") -> _TodoistClient | dict[str, str]:
        """Get a Todoist client, or return an error dict if no credentials."""
        api_key = _get_api_key(account)
        if not api_key:
            return {
                "error": "Todoist credentials not configured",
                "help": (
                    "Set TODOIST_API_KEY environment variable or configure via credential store"
                ),
            }
        return _TodoistClient(api_key)

    @mcp.tool()
    def todoist_list_tasks(
        project_id: str | None = None,
        label: str | None = None,
        filter_query: str | None = None,
        account: str = "",
    ) -> dict:
        """
        List all active tasks with optional filtering.

        Args:
            project_id: Filter tasks by project ID
            label: Filter tasks by label name
            filter_query: Filter using Todoist filter syntax (e.g., "today | overdue")

        Returns:
            Dict with list of tasks or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_tasks(
                project_id=project_id, label=label, filter_query=filter_query
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"tasks": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_get_task(task_id: str, account: str = "") -> dict:
        """
        Get details of a specific task.

        Args:
            task_id: Task ID

        Returns:
            Dict with task details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_task(task_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"task": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_create_task(
        content: str,
        description: str | None = None,
        project_id: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int = 1,
        labels: list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Create a new task.

        Args:
            content: Task content/title (required)
            description: Task description
            project_id: Project ID to add task to
            due_string: Human-readable due date (e.g., "tomorrow", "next Monday")
            due_date: Due date in YYYY-MM-DD format
            priority: Priority from 1 (normal) to 4 (urgent)
            labels: List of label names

        Returns:
            Dict with created task details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_task(
                content=content,
                description=description,
                project_id=project_id,
                due_string=due_string,
                due_date=due_date,
                priority=priority,
                labels=labels,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"task": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_update_task(
        task_id: str,
        content: str | None = None,
        description: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Update an existing task.

        Args:
            task_id: Task ID (required)
            content: New task content/title
            description: New task description
            due_string: New human-readable due date
            due_date: New due date in YYYY-MM-DD format
            priority: New priority from 1 (normal) to 4 (urgent)
            labels: New list of label names

        Returns:
            Dict with updated task details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.update_task(
                task_id=task_id,
                content=content,
                description=description,
                due_string=due_string,
                due_date=due_date,
                priority=priority,
                labels=labels,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"task": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_complete_task(task_id: str, account: str = "") -> dict:
        """
        Mark a task as complete.

        Args:
            task_id: Task ID

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.complete_task(task_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "completed_task_id": task_id}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_delete_task(task_id: str, account: str = "") -> dict:
        """
        Delete a task.

        Args:
            task_id: Task ID

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_task(task_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "deleted_task_id": task_id}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_list_projects(account: str = "") -> dict:
        """
        List all projects.

        Returns:
            Dict with list of projects or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_projects()
            if isinstance(result, dict) and "error" in result:
                return result
            return {"projects": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def todoist_create_project(
        name: str,
        color: str | None = None,
        is_favorite: bool = False,
        account: str = "",
    ) -> dict:
        """
        Create a new project.

        Args:
            name: Project name (required)
            color: Project color (e.g., "red", "blue", "green")
            is_favorite: Whether to mark as favorite

        Returns:
            Dict with created project details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_project(name=name, color=color, is_favorite=is_favorite)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"project": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
