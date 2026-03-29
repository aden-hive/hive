"""Terraform Cloud / HCP Terraform API integration.

Provides workspace and run management via the Terraform Cloud REST API v2.
Requires TFC_TOKEN (and optionally TFC_URL for Terraform Enterprise).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

DEFAULT_URL = "https://app.terraform.io"


def _get_config() -> tuple[str, dict] | dict:
    """Return (base_url, headers) or error dict."""
    token = os.getenv("TFC_TOKEN", "")
    if not token:
        return {"error": "TFC_TOKEN is required", "help": "Set TFC_TOKEN environment variable"}
    url = os.getenv("TFC_URL", DEFAULT_URL).rstrip("/")
    base_url = f"{url}/api/v2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
    }
    return base_url, headers


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, headers: dict, payload: dict) -> dict:
    """Send a POST request."""
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_workspace(ws: dict) -> dict:
    """Extract key fields from a JSON:API workspace resource."""
    attrs = ws.get("attributes", {})
    return {
        "id": ws.get("id"),
        "name": attrs.get("name"),
        "terraform_version": attrs.get("terraform-version"),
        "execution_mode": attrs.get("execution-mode"),
        "auto_apply": attrs.get("auto-apply"),
        "locked": attrs.get("locked"),
        "resource_count": attrs.get("resource-count"),
        "created_at": attrs.get("created-at"),
        "updated_at": attrs.get("updated-at"),
    }


def _extract_run(run: dict) -> dict:
    """Extract key fields from a JSON:API run resource."""
    attrs = run.get("attributes", {})
    return {
        "id": run.get("id"),
        "status": attrs.get("status"),
        "message": attrs.get("message"),
        "source": attrs.get("source"),
        "trigger_reason": attrs.get("trigger-reason"),
        "is_destroy": attrs.get("is-destroy"),
        "plan_only": attrs.get("plan-only"),
        "has_changes": attrs.get("has-changes"),
        "auto_apply": attrs.get("auto-apply"),
        "created_at": attrs.get("created-at"),
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Terraform Cloud tools."""

    @mcp.tool()
    def terraform_list_workspaces(
        organization: str,
        search: str = "",
        page_size: int = 20,
        page_number: int = 1,
    ) -> dict:
        """List workspaces in a Terraform Cloud organization.

        Args:
            organization: Organization name.
            search: Search workspaces by name.
            page_size: Results per page (max 100, default 20).
            page_number: Page number (default 1).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not organization:
            return {"error": "organization is required"}

        params: dict[str, Any] = {
            "page[size]": min(page_size, 100),
            "page[number]": page_number,
        }
        if search:
            params["search[name]"] = search

        data = _get(f"{base_url}/organizations/{organization}/workspaces", headers, params)
        if "error" in data:
            return data

        workspaces = data.get("data", [])
        meta = data.get("meta", {}).get("pagination", {})
        return {
            "count": len(workspaces),
            "total_count": meta.get("total-count"),
            "total_pages": meta.get("total-pages"),
            "workspaces": [_extract_workspace(ws) for ws in workspaces],
        }

    @mcp.tool()
    def terraform_get_workspace(workspace_id: str) -> dict:
        """Get details of a specific Terraform Cloud workspace.

        Args:
            workspace_id: The workspace ID (e.g. 'ws-abc123').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not workspace_id:
            return {"error": "workspace_id is required"}

        data = _get(f"{base_url}/workspaces/{workspace_id}", headers)
        if "error" in data:
            return data

        ws = data.get("data", {})
        result = _extract_workspace(ws)
        attrs = ws.get("attributes", {})
        result["description"] = attrs.get("description")
        result["vcs_repo"] = attrs.get("vcs-repo")
        result["working_directory"] = attrs.get("working-directory")
        return result

    @mcp.tool()
    def terraform_list_runs(
        workspace_id: str,
        status: str = "",
        page_size: int = 20,
        page_number: int = 1,
    ) -> dict:
        """List runs for a Terraform Cloud workspace.

        Args:
            workspace_id: The workspace ID.
            status: Filter by status (e.g. 'applied', 'planned', 'errored').
            page_size: Results per page (max 100, default 20).
            page_number: Page number (default 1).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not workspace_id:
            return {"error": "workspace_id is required"}

        params: dict[str, Any] = {
            "page[size]": min(page_size, 100),
            "page[number]": page_number,
        }
        if status:
            params["filter[status]"] = status

        data = _get(f"{base_url}/workspaces/{workspace_id}/runs", headers, params)
        if "error" in data:
            return data

        runs = data.get("data", [])
        meta = data.get("meta", {}).get("pagination", {})
        return {
            "count": len(runs),
            "total_count": meta.get("total-count"),
            "total_pages": meta.get("total-pages"),
            "runs": [_extract_run(r) for r in runs],
        }

    @mcp.tool()
    def terraform_get_run(run_id: str) -> dict:
        """Get details of a specific Terraform Cloud run.

        Args:
            run_id: The run ID (e.g. 'run-abc123').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not run_id:
            return {"error": "run_id is required"}

        data = _get(f"{base_url}/runs/{run_id}", headers)
        if "error" in data:
            return data

        run = data.get("data", {})
        result = _extract_run(run)
        attrs = run.get("attributes", {})
        result["plan_and_apply"] = {
            "resource_additions": attrs.get("status-timestamps", {}).get("plan-queued-at"),
        }
        result["permissions"] = attrs.get("permissions", {})
        return result

    @mcp.tool()
    def terraform_create_run(
        workspace_id: str,
        message: str = "Triggered via API",
        auto_apply: bool = False,
        is_destroy: bool = False,
        plan_only: bool = False,
    ) -> dict:
        """Trigger a new run in a Terraform Cloud workspace.

        Args:
            workspace_id: The workspace ID.
            message: Run message/reason.
            auto_apply: Automatically apply after plan succeeds.
            is_destroy: Run a destroy plan.
            plan_only: Only run a plan (no apply).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not workspace_id:
            return {"error": "workspace_id is required"}

        payload = {
            "data": {
                "type": "runs",
                "attributes": {
                    "message": message,
                    "auto-apply": auto_apply,
                    "is-destroy": is_destroy,
                    "plan-only": plan_only,
                },
                "relationships": {
                    "workspace": {
                        "data": {
                            "type": "workspaces",
                            "id": workspace_id,
                        }
                    }
                },
            }
        }

        data = _post(f"{base_url}/runs", headers, payload)
        if "error" in data:
            return data

        run = data.get("data", {})
        return _extract_run(run)
