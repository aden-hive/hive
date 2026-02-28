cat > power_bi_tool.py << 'EOF'
"""
Power BI Tool - Dataset Refresh and Report Export

Supports Power BI REST API for:
- Refreshing datasets
- Exporting reports
- Managing workspaces

API Reference: https://learn.microsoft.com/en-us/rest/api/power-bi/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

POWER_BI_API_BASE = "https://api.powerbi.com/v1.0/myorg"


class _PowerBIClient:
    """Internal client wrapping Power BI REST API calls."""

    def __init__(self, access_token: str):
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Power BI access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded"}
        if response.status_code == 202:
            return {
                "status": "accepted",
                "request_id": response.headers.get("x-ms-request-id")
            }
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Power BI API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def get_workspaces(self) -> dict[str, Any]:
        """Get list of Power BI workspaces."""
        response = httpx.get(
            f"{POWER_BI_API_BASE}/groups",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def refresh_dataset(self, workspace_id: str, dataset_id: str) -> dict[str, Any]:
        """Trigger a dataset refresh."""
        response = httpx.post(
            f"{POWER_BI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/refreshes",
            headers=self._headers,
            json={"notifyOption": "NoNotification"},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_datasets(self, workspace_id: str) -> dict[str, Any]:
        """Get list of datasets in a workspace."""
        response = httpx.get(
            f"{POWER_BI_API_BASE}/groups/{workspace_id}/datasets",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_reports(self, workspace_id: str) -> dict[str, Any]:
        """Get list of reports in a workspace."""
        response = httpx.get(
            f"{POWER_BI_API_BASE}/groups/{workspace_id}/reports",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def export_report(
        self, workspace_id: str, report_id: str, export_format: str = "PDF"
    ) -> dict[str, Any]:
        """Export a report to PDF, PPTX, or PNG."""
        if export_format.upper() not in ["PDF", "PPTX", "PNG"]:
            return {"error": f"Invalid format: {export_format}. Must be PDF, PPTX, or PNG"}
        
        response = httpx.post(
            f"{POWER_BI_API_BASE}/groups/{workspace_id}/reports/{report_id}/ExportTo",
            headers=self._headers,
            json={"format": export_format.upper()},
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Power BI tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Power BI access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("power_bi")
            if token is not None and not isinstance(token, str):
                raise TypeError(f"Expected string from credentials, got {type(token).__name__}")
            return token
        return os.getenv("POWER_BI_ACCESS_TOKEN")

    def _get_client() -> _PowerBIClient | dict[str, str]:
        """Get a Power BI client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Power BI credentials not configured",
                "help": "Set POWER_BI_ACCESS_TOKEN environment variable or configure via credential store",
            }
        return _PowerBIClient(token)

    @mcp.tool()
    def power_bi_get_workspaces() -> dict:
        """
        Get list of Power BI workspaces.

        Returns:
            Dict with list of workspaces or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_workspaces()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def power_bi_refresh_dataset(workspace_id: str, dataset_id: str) -> dict:
        """
        Refresh a Power BI dataset.

        Args:
            workspace_id: The Power BI workspace ID
            dataset_id: The dataset ID to refresh

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.refresh_dataset(workspace_id, dataset_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def power_bi_get_datasets(workspace_id: str) -> dict:
        """
        Get list of datasets in a Power BI workspace.

        Args:
            workspace_id: The Power BI workspace ID

        Returns:
            Dict with list of datasets or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_datasets(workspace_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def power_bi_get_reports(workspace_id: str) -> dict:
        """
        Get list of reports in a Power BI workspace.

        Args:
            workspace_id: The Power BI workspace ID

        Returns:
            Dict with list of reports or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_reports(workspace_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def power_bi_export_report(
        workspace_id: str, report_id: str, export_format: str = "PDF"
    ) -> dict:
        """
        Export a Power BI report to PDF, PPTX, or PNG.

        Args:
            workspace_id: The Power BI workspace ID
            report_id: The report ID to export
            export_format: Export format - "PDF", "PPTX", or "PNG" (default: "PDF")

        Returns:
            Dict with export result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.export_report(workspace_id, report_id, export_format)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
EOF
