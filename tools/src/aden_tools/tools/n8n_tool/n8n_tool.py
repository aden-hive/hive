"""
n8n Tool - Trigger workflows and check execution status via n8n API.

Supports:
- API Key authentication (N8N_API_KEY + N8N_API_URL)
- OAuth2 tokens via the credential store

API Reference: https://docs.n8n.io/api/

MVP Scope (per issue #2931):
- Trigger workflow execution (webhook or n8n API: execute workflow by ID)
- Get execution status (run ID, status: success/failed/running)
- Optional: list workflows (for discovery or dynamic trigger)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _N8nClient:
    """Internal client wrapping n8n API calls."""

    def __init__(self, api_url: str, api_key: str):
        """Initialize n8n client.

        Args:
            api_url: Base URL of n8n instance (e.g., 'https://n8n.example.com')
            api_key: n8n API key for authentication
        """
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-N8N-API-KEY": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle n8n API response format."""
        if response.status_code == 401:
            return {"error": "Invalid n8n API key", "status_code": 401}
        if response.status_code == 404:
            return {"error": "Resource not found", "status_code": 404}
        if response.status_code >= 400:
            try:
                error_data = response.json()
                return {
                    "error": error_data.get("message", f"HTTP error {response.status_code}"),
                    "status_code": response.status_code,
                }
            except Exception:
                return {"error": f"HTTP error {response.status_code}: {response.text}"}

        try:
            return response.json()
        except Exception:
            return {"error": f"Invalid JSON response: {response.text}"}

    # ============================================================
    # Core MVP Functions
    # ============================================================

    def execute_workflow(
        self,
        workflow_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow by ID via n8n API.

        Args:
            workflow_id: The workflow ID to execute
            data: Optional input data to pass to the workflow

        Returns:
            Dict with execution details (id, status, data) or error
        """
        url = f"{self._api_url}/api/v1/workflows/{workflow_id}/execute"
        body = data or {}

        response = httpx.post(
            url,
            headers=self._headers,
            json=body,
            timeout=60.0,  # Workflows may take time
        )
        return self._handle_response(response)

    def trigger_webhook(
        self,
        webhook_path: str,
        data: dict[str, Any] | None = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        """Trigger a workflow via webhook URL.

        Args:
            webhook_path: The webhook path (e.g., 'my-webhook' or full URL)
            data: Optional payload data
            method: HTTP method (POST or GET)

        Returns:
            Dict with response or error
        """
        # Handle both full URLs and paths
        if webhook_path.startswith("http"):
            url = webhook_path
        else:
            url = f"{self._api_url}/webhook/{webhook_path}"

        if method.upper() == "GET":
            response = httpx.get(url, params=data or {}, timeout=60.0)
        else:
            response = httpx.post(
                url,
                json=data or {},
                timeout=60.0,
            )

        # Webhooks may return non-JSON responses
        if response.status_code >= 400:
            return {"error": f"Webhook failed: {response.status_code}", "body": response.text}

        try:
            return {"success": True, "data": response.json()}
        except Exception:
            return {"success": True, "data": response.text}

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        """Get execution status and details by ID.

        Args:
            execution_id: The execution ID

        Returns:
            Dict with execution status (id, status, startedAt, stoppedAt, data) or error
        """
        url = f"{self._api_url}/api/v1/executions/{execution_id}"

        response = httpx.get(
            url,
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_executions(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List workflow executions with optional filters.

        Args:
            workflow_id: Optional workflow ID to filter by
            status: Optional status filter ('success', 'error', 'waiting', 'running')
            limit: Maximum number of executions to return (default 20)

        Returns:
            Dict with list of executions or error
        """
        url = f"{self._api_url}/api/v1/executions"
        params: dict[str, Any] = {"limit": min(limit, 250)}

        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status

        response = httpx.get(
            url,
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_workflows(
        self,
        active: bool | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List available workflows.

        Args:
            active: Optional filter for active/inactive workflows
            limit: Maximum number of workflows to return (default 50)

        Returns:
            Dict with list of workflows (id, name, active, createdAt) or error
        """
        url = f"{self._api_url}/api/v1/workflows"
        params: dict[str, Any] = {"limit": min(limit, 250)}

        if active is not None:
            params["active"] = str(active).lower()

        response = httpx.get(
            url,
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Get workflow details by ID.

        Args:
            workflow_id: The workflow ID

        Returns:
            Dict with workflow details (id, name, active, nodes, etc.) or error
        """
        url = f"{self._api_url}/api/v1/workflows/{workflow_id}"

        response = httpx.get(
            url,
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def activate_workflow(self, workflow_id: str, active: bool = True) -> dict[str, Any]:
        """Activate or deactivate a workflow.

        Args:
            workflow_id: The workflow ID
            active: True to activate, False to deactivate

        Returns:
            Dict with updated workflow or error
        """
        url = f"{self._api_url}/api/v1/workflows/{workflow_id}"

        response = httpx.patch(
            url,
            headers=self._headers,
            json={"active": active},
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register n8n tools with the MCP server."""

    def _get_config() -> tuple[str | None, str | None]:
        """Get n8n API URL and key from credential manager or environment."""
        api_url = None
        api_key = None

        if credentials is not None:
            # Try to get from credential store
            creds = credentials.get("n8n")
            if isinstance(creds, dict):
                api_url = creds.get("api_url") or creds.get("url")
                api_key = creds.get("api_key") or creds.get("key")
            elif isinstance(creds, str):
                # Assume it's the API key, URL from env
                api_key = creds

        # Fall back to environment variables
        if not api_url:
            api_url = os.getenv("N8N_API_URL") or os.getenv("N8N_URL")
        if not api_key:
            api_key = os.getenv("N8N_API_KEY")

        return api_url, api_key

    def _get_client() -> _N8nClient | dict[str, str]:
        """Get an n8n client, or return an error dict if no credentials."""
        api_url, api_key = _get_config()

        if not api_url:
            return {
                "error": "n8n API URL not configured",
                "help": "Set N8N_API_URL environment variable or configure via credential store",
            }
        if not api_key:
            return {
                "error": "n8n API key not configured",
                "help": "Set N8N_API_KEY environment variable or configure via credential store",
            }

        return _N8nClient(api_url, api_key)

    # ============================================================
    # MVP Tools
    # ============================================================

    @mcp.tool()
    def n8n_execute_workflow(
        workflow_id: str,
        data: dict | None = None,
    ) -> dict:
        """
        Execute a workflow by ID via n8n API.

        Use this when you need to trigger an n8n workflow programmatically.
        The workflow must exist and be accessible via the configured n8n instance.

        Args:
            workflow_id: The workflow ID to execute (e.g., '5' or 'abc123')
            data: Optional input data to pass to the workflow as JSON

        Returns:
            Dict with execution details including execution ID and status,
            or error message if execution failed
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.execute_workflow(workflow_id, data)
            if "error" in result:
                return result
            return {
                "success": True,
                "execution_id": result.get("id"),
                "status": result.get("status", "unknown"),
                "data": result.get("data"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out - workflow may still be running"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_trigger_webhook(
        webhook_path: str,
        data: dict | None = None,
        method: str = "POST",
    ) -> dict:
        """
        Trigger a workflow via its webhook URL.

        Use this when you need to trigger an n8n workflow that has a Webhook trigger node.
        This is the preferred method for production workflows.

        Args:
            webhook_path: The webhook path (e.g., 'my-workflow-webhook') or full URL
            data: Optional JSON payload to send
            method: HTTP method - 'POST' (default) or 'GET'

        Returns:
            Dict with webhook response data or error message
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.trigger_webhook(webhook_path, data, method)
            return result
        except httpx.TimeoutException:
            return {"error": "Webhook request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_get_execution_status(
        execution_id: str,
    ) -> dict:
        """
        Get the status and details of a workflow execution.

        Use this to check if a triggered workflow has completed, failed,
        or is still running. Also retrieves output data from completed executions.

        Args:
            execution_id: The execution ID returned from execute_workflow or found in execution list

        Returns:
            Dict with execution details:
            - id: Execution ID
            - status: 'success', 'error', 'running', 'waiting'
            - startedAt: When execution started
            - stoppedAt: When execution completed (if finished)
            - data: Output data from the workflow (if completed)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_execution(execution_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "execution": {
                    "id": result.get("id"),
                    "status": result.get("status"),
                    "mode": result.get("mode"),
                    "startedAt": result.get("startedAt"),
                    "stoppedAt": result.get("stoppedAt"),
                    "workflowId": result.get("workflowId"),
                    "finished": result.get("finished", False),
                    "data": result.get("data"),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_list_executions(
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        List recent workflow executions with optional filters.

        Use this to monitor execution history, find failed runs,
        or check the status of multiple workflows.

        Args:
            workflow_id: Optional - filter by specific workflow ID
            status: Optional - filter by status ('success', 'error', 'waiting', 'running')
            limit: Maximum number of executions to return (1-250, default 20)

        Returns:
            Dict with list of executions, each containing id, status, workflowId, etc.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_executions(workflow_id, status, limit)
            if "error" in result:
                return result
            executions = result.get("data", [])
            return {
                "success": True,
                "count": len(executions),
                "executions": [
                    {
                        "id": ex.get("id"),
                        "status": ex.get("status"),
                        "workflowId": ex.get("workflowId"),
                        "startedAt": ex.get("startedAt"),
                        "stoppedAt": ex.get("stoppedAt"),
                        "finished": ex.get("finished", False),
                    }
                    for ex in executions
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_list_workflows(
        active_only: bool = False,
        limit: int = 50,
    ) -> dict:
        """
        List available workflows in the n8n instance.

        Use this for discovery - to find workflow IDs for triggering,
        or to see what workflows are available and their status.

        Args:
            active_only: If True, only return active (enabled) workflows
            limit: Maximum number of workflows to return (1-250, default 50)

        Returns:
            Dict with list of workflows, each containing id, name, active status, etc.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_workflows(active=True if active_only else None, limit=limit)
            if "error" in result:
                return result
            workflows = result.get("data", [])
            return {
                "success": True,
                "count": len(workflows),
                "workflows": [
                    {
                        "id": wf.get("id"),
                        "name": wf.get("name"),
                        "active": wf.get("active", False),
                        "createdAt": wf.get("createdAt"),
                        "updatedAt": wf.get("updatedAt"),
                    }
                    for wf in workflows
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_get_workflow(
        workflow_id: str,
    ) -> dict:
        """
        Get detailed information about a specific workflow.

        Use this to inspect a workflow's configuration, nodes,
        and settings before triggering it.

        Args:
            workflow_id: The workflow ID to retrieve

        Returns:
            Dict with workflow details including name, nodes, active status, etc.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_workflow(workflow_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "workflow": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "active": result.get("active", False),
                    "createdAt": result.get("createdAt"),
                    "updatedAt": result.get("updatedAt"),
                    "nodes": [
                        {"name": n.get("name"), "type": n.get("type")}
                        for n in result.get("nodes", [])
                    ],
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_activate_workflow(
        workflow_id: str,
        active: bool = True,
    ) -> dict:
        """
        Activate or deactivate a workflow.

        Use this to enable/disable workflows programmatically.
        Active workflows can be triggered; inactive ones cannot.

        Args:
            workflow_id: The workflow ID to modify
            active: True to activate, False to deactivate

        Returns:
            Dict with updated workflow status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.activate_workflow(workflow_id, active)
            if "error" in result:
                return result
            return {
                "success": True,
                "workflow": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "active": result.get("active", False),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
