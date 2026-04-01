"""
n8n Workflow Automation Tool - Workflows and executions management.

Supports:
- API key authentication (N8N_API_KEY) via X-N8N-API-KEY header
- Self-hosted or n8n Cloud instances (N8N_BASE_URL)

API Reference: https://docs.n8n.io/api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str] | dict[str, str]:
    """Return (api_key, base_url) or an error dict."""
    if credentials is not None:
        api_key = credentials.get("n8n")
        base_url = credentials.get("n8n_base_url")
    else:
        api_key = os.getenv("N8N_API_KEY")
        base_url = os.getenv("N8N_BASE_URL")

    if not api_key or not base_url:
        return {
            "error": "n8n credentials not configured",
            "help": (
                "Set N8N_API_KEY and N8N_BASE_URL environment variables "
                "or configure via credential store"
            ),
        }
    base_url = base_url.rstrip("/")
    return api_key, base_url


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-N8N-API-KEY": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 204:
        return {"success": True}
    if resp.status_code == 401:
        return {"error": "Invalid n8n API key"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this n8n resource"}
    if resp.status_code == 404:
        return {"error": "n8n resource not found"}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", resp.text)
        except Exception:
            detail = resp.text
        return {"error": f"n8n API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register n8n workflow automation tools with the MCP server."""

    @mcp.tool()
    def n8n_list_workflows(
        active: str = "",
        tags: str = "",
        name: str = "",
        limit: int = 100,
        cursor: str = "",
    ) -> dict:
        """
        List n8n workflows with optional filters.

        Args:
            active: Filter by active status - "true" or "false" (empty for all).
            tags: Comma-separated tag names to filter by (e.g. "production,test").
            name: Filter by workflow name (partial match).
            limit: Max workflows per page (1-250, default 100).
            cursor: Pagination cursor from a previous response.

        Returns:
            Dict with workflow list and pagination cursor.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        try:
            params: dict[str, Any] = {"limit": min(limit, 250)}
            if active:
                params["active"] = active
            if tags:
                params["tags"] = tags
            if name:
                params["name"] = name
            if cursor:
                params["cursor"] = cursor

            resp = httpx.get(
                f"{base_url}/api/v1/workflows",
                headers=_headers(api_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            workflows = []
            for w in result.get("data", []):
                tag_names = [t.get("name", "") for t in w.get("tags", [])]
                workflows.append(
                    {
                        "id": w.get("id"),
                        "name": w.get("name"),
                        "active": w.get("active"),
                        "created_at": w.get("createdAt"),
                        "updated_at": w.get("updatedAt"),
                        "tags": tag_names,
                        "node_count": len(w.get("nodes", [])),
                    }
                )

            output: dict[str, Any] = {
                "count": len(workflows),
                "workflows": workflows,
            }
            next_cursor = result.get("nextCursor")
            if next_cursor:
                output["next_cursor"] = next_cursor
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_get_workflow(workflow_id: str) -> dict:
        """
        Get details of a specific n8n workflow.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Dict with full workflow details including nodes and connections.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not workflow_id:
            return {"error": "workflow_id is required"}

        try:
            resp = httpx.get(
                f"{base_url}/api/v1/workflows/{workflow_id}",
                headers=_headers(api_key),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            tag_names = [t.get("name", "") for t in result.get("tags", [])]
            nodes = []
            for n in result.get("nodes", []):
                nodes.append(
                    {
                        "name": n.get("name"),
                        "type": n.get("type"),
                        "position": n.get("position"),
                    }
                )

            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "active": result.get("active"),
                "created_at": result.get("createdAt"),
                "updated_at": result.get("updatedAt"),
                "tags": tag_names,
                "nodes": nodes,
                "node_count": len(nodes),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_activate_workflow(workflow_id: str) -> dict:
        """
        Activate (publish) an n8n workflow.

        Args:
            workflow_id: The workflow ID to activate.

        Returns:
            Dict with updated workflow status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not workflow_id:
            return {"error": "workflow_id is required"}

        try:
            resp = httpx.post(
                f"{base_url}/api/v1/workflows/{workflow_id}/activate",
                headers=_headers(api_key),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "active": result.get("active"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_deactivate_workflow(workflow_id: str) -> dict:
        """
        Deactivate an n8n workflow.

        Args:
            workflow_id: The workflow ID to deactivate.

        Returns:
            Dict with updated workflow status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not workflow_id:
            return {"error": "workflow_id is required"}

        try:
            resp = httpx.post(
                f"{base_url}/api/v1/workflows/{workflow_id}/deactivate",
                headers=_headers(api_key),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "active": result.get("active"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_list_executions(
        workflow_id: str = "",
        status: str = "",
        limit: int = 100,
        cursor: str = "",
    ) -> dict:
        """
        List n8n workflow executions with optional filters.

        Args:
            workflow_id: Filter by workflow ID (optional).
            status: Filter by status - "success", "error", "running",
                    "waiting", or "canceled" (optional).
            limit: Max executions per page (1-250, default 100).
            cursor: Pagination cursor from a previous response.

        Returns:
            Dict with execution list and pagination cursor.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        try:
            params: dict[str, Any] = {"limit": min(limit, 250)}
            if workflow_id:
                params["workflowId"] = workflow_id
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor

            resp = httpx.get(
                f"{base_url}/api/v1/executions",
                headers=_headers(api_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            executions = []
            for e in result.get("data", []):
                executions.append(
                    {
                        "id": e.get("id"),
                        "workflow_id": e.get("workflowId"),
                        "status": e.get("status"),
                        "mode": e.get("mode"),
                        "finished": e.get("finished"),
                        "started_at": e.get("startedAt"),
                        "stopped_at": e.get("stoppedAt"),
                    }
                )

            output: dict[str, Any] = {
                "count": len(executions),
                "executions": executions,
            }
            next_cursor = result.get("nextCursor")
            if next_cursor:
                output["next_cursor"] = next_cursor
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def n8n_get_execution(
        execution_id: str,
        include_data: bool = False,
    ) -> dict:
        """
        Get details of a specific n8n execution.

        Args:
            execution_id: The execution ID.
            include_data: Whether to include detailed execution data (default false).

        Returns:
            Dict with execution details.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not execution_id:
            return {"error": "execution_id is required"}

        try:
            params: dict[str, Any] = {}
            if include_data:
                params["includeData"] = "true"

            resp = httpx.get(
                f"{base_url}/api/v1/executions/{execution_id}",
                headers=_headers(api_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            output: dict[str, Any] = {
                "id": result.get("id"),
                "workflow_id": result.get("workflowId"),
                "status": result.get("status"),
                "mode": result.get("mode"),
                "finished": result.get("finished"),
                "started_at": result.get("startedAt"),
                "stopped_at": result.get("stoppedAt"),
                "retry_of": result.get("retryOf"),
                "retry_success_id": result.get("retrySuccessId"),
            }
            if include_data and "data" in result:
                output["data"] = result["data"]
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
