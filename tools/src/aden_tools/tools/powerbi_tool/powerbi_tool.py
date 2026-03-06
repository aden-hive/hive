"""Microsoft Power BI REST API integration.

Provides workspace, dataset, and report management via the Power BI REST API v1.0.
Requires POWERBI_ACCESS_TOKEN (OAuth2 Bearer token).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.powerbi.com/v1.0/myorg"


def _get_headers() -> dict | None:
    """Return headers dict or None if token missing."""
    token = os.getenv("POWERBI_ACCESS_TOKEN", "")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, headers: dict, payload: dict | None = None) -> dict:
    """Send a POST request."""
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    if resp.status_code == 202:
        return {"result": "accepted", "request_id": resp.headers.get("x-ms-request-id", "")}
    if not resp.content:
        return {"result": "ok"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Power BI tools."""

    @mcp.tool()
    def powerbi_list_workspaces(
        search: str = "",
        top: int = 100,
        skip: int = 0,
    ) -> dict:
        """List Power BI workspaces (groups).

        Args:
            search: Filter workspaces by name (contains search).
            top: Max results to return (default 100).
            skip: Number of results to skip for pagination.
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "POWERBI_ACCESS_TOKEN is required",
                "help": "Set POWERBI_ACCESS_TOKEN environment variable",
            }

        params: dict[str, Any] = {"$top": top, "$skip": skip}
        if search:
            params["$filter"] = f"contains(name,'{search}')"

        data = _get(f"{BASE_URL}/groups", headers, params)
        if "error" in data:
            return data

        groups = data.get("value", [])
        return {
            "count": len(groups),
            "workspaces": [
                {
                    "id": g.get("id"),
                    "name": g.get("name"),
                    "is_read_only": g.get("isReadOnly"),
                    "is_on_dedicated_capacity": g.get("isOnDedicatedCapacity"),
                }
                for g in groups
            ],
        }

    @mcp.tool()
    def powerbi_list_datasets(workspace_id: str) -> dict:
        """List datasets in a Power BI workspace.

        Args:
            workspace_id: The workspace/group ID.
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "POWERBI_ACCESS_TOKEN is required",
                "help": "Set POWERBI_ACCESS_TOKEN environment variable",
            }
        if not workspace_id:
            return {"error": "workspace_id is required"}

        data = _get(f"{BASE_URL}/groups/{workspace_id}/datasets", headers)
        if "error" in data:
            return data

        datasets = data.get("value", [])
        return {
            "count": len(datasets),
            "datasets": [
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "configured_by": d.get("configuredBy"),
                    "is_refreshable": d.get("isRefreshable"),
                    "created_date": d.get("createdDate"),
                    "description": d.get("description"),
                    "web_url": d.get("webUrl"),
                }
                for d in datasets
            ],
        }

    @mcp.tool()
    def powerbi_list_reports(workspace_id: str) -> dict:
        """List reports in a Power BI workspace.

        Args:
            workspace_id: The workspace/group ID.
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "POWERBI_ACCESS_TOKEN is required",
                "help": "Set POWERBI_ACCESS_TOKEN environment variable",
            }
        if not workspace_id:
            return {"error": "workspace_id is required"}

        data = _get(f"{BASE_URL}/groups/{workspace_id}/reports", headers)
        if "error" in data:
            return data

        reports = data.get("value", [])
        return {
            "count": len(reports),
            "reports": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "dataset_id": r.get("datasetId"),
                    "report_type": r.get("reportType"),
                    "web_url": r.get("webUrl"),
                    "description": r.get("description"),
                }
                for r in reports
            ],
        }

    @mcp.tool()
    def powerbi_refresh_dataset(
        workspace_id: str,
        dataset_id: str,
        notify_option: str = "NoNotification",
    ) -> dict:
        """Trigger a refresh for a Power BI dataset.

        Args:
            workspace_id: The workspace/group ID.
            dataset_id: The dataset ID.
            notify_option: Notification option: NoNotification, MailOnFailure, MailOnCompletion.
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "POWERBI_ACCESS_TOKEN is required",
                "help": "Set POWERBI_ACCESS_TOKEN environment variable",
            }
        if not workspace_id or not dataset_id:
            return {"error": "workspace_id and dataset_id are required"}

        payload = {"notifyOption": notify_option}
        data = _post(
            f"{BASE_URL}/groups/{workspace_id}/datasets/{dataset_id}/refreshes",
            headers,
            payload,
        )
        return data

    @mcp.tool()
    def powerbi_get_refresh_history(
        workspace_id: str,
        dataset_id: str,
        top: int = 10,
    ) -> dict:
        """Get refresh history for a Power BI dataset.

        Args:
            workspace_id: The workspace/group ID.
            dataset_id: The dataset ID.
            top: Number of recent refresh entries to return (default 10).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "POWERBI_ACCESS_TOKEN is required",
                "help": "Set POWERBI_ACCESS_TOKEN environment variable",
            }
        if not workspace_id or not dataset_id:
            return {"error": "workspace_id and dataset_id are required"}

        params = {"$top": top}
        data = _get(
            f"{BASE_URL}/groups/{workspace_id}/datasets/{dataset_id}/refreshes",
            headers,
            params,
        )
        if "error" in data:
            return data

        refreshes = data.get("value", [])
        return {
            "count": len(refreshes),
            "refreshes": [
                {
                    "request_id": r.get("requestId"),
                    "refresh_type": r.get("refreshType"),
                    "status": r.get("status"),
                    "start_time": r.get("startTime"),
                    "end_time": r.get("endTime"),
                }
                for r in refreshes
            ],
        }
