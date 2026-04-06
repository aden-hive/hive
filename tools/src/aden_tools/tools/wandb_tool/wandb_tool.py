"""
Weights & Biases ML experiment tracking tool.

Supports:
- HTTP Bearer Auth with WANDB_API_KEY
- Cloud (api.wandb.ai) instances

API Reference: https://docs.wandb.ai/ref/app/pages/run-page
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_HOST = "https://api.wandb.ai"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str] | dict[str, Any]:
    """Return (api_key, host) or an error dict."""
    if credentials is not None:
        api_key = credentials.get("wandb_api_key")
        try:
            host = credentials.get("wandb_host") or os.getenv("WANDB_HOST") or DEFAULT_HOST
        except KeyError:
            host = os.getenv("WANDB_HOST") or DEFAULT_HOST
    else:
        api_key = os.getenv("WANDB_API_KEY")
        host = os.getenv("WANDB_HOST") or DEFAULT_HOST

    if not api_key:
        return {
            "error": "Weights & Biases credentials not configured",
            "help": ("Set WANDB_API_KEY environment variable or configure via credential store"),
        }
    host = host.rstrip("/")
    return api_key, host


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 401:
        return {"error": "Invalid Weights & Biases API key"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this Weights & Biases resource"}
    if resp.status_code == 404:
        return {"error": "Weights & Biases resource not found"}
    if resp.status_code == 429:
        return {"error": "Weights & Biases rate limit exceeded. Try again later."}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", body.get("error", resp.text))
        except Exception:
            detail = resp.text
        return {"error": f"Weights & Biases API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Weights & Biases experiment tracking tools with the MCP server."""

    @mcp.tool()
    def wandb_list_projects(entity: str) -> dict:
        """
        List all projects for a Weights & Biases entity (user or organization).

        Args:
            entity: The W&B entity name (username or organization).

        Returns:
            Dict containing the list of projects for the entity.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/projects",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"entity": entity},
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_list_runs(
        entity: str,
        project: str,
        filters: str = "",
        per_page: int = 50,
    ) -> dict:
        """
        List runs in a Weights & Biases project.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            filters: Optional JSON filter string to narrow results.
            per_page: Number of runs per page (default 50).

        Returns:
            Dict containing the list of runs in the project.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            params: dict[str, Any] = {"per_page": per_page}
            if filters:
                params["filters"] = filters

            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}",
                headers={"Authorization": f"Bearer {api_key}"},
                params=params,
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_get_run(entity: str, project: str, run_id: str) -> dict:
        """
        Get details of a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing full run details including config and metadata.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}/{run_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_get_run_metrics(
        entity: str,
        project: str,
        run_id: str,
        metric_keys: str = "",
    ) -> dict:
        """
        Get metrics history for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.
            metric_keys: Optional comma-separated list of metric keys to filter.

        Returns:
            Dict containing the run's metric history.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            params: dict[str, Any] = {}
            if metric_keys:
                params["keys"] = metric_keys

            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}/{run_id}/history",
                headers={"Authorization": f"Bearer {api_key}"},
                params=params,
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_list_artifacts(entity: str, project: str, run_id: str) -> dict:
        """
        List artifacts for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing the list of artifacts logged by the run.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}/{run_id}/artifacts",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_get_summary(entity: str, project: str, run_id: str) -> dict:
        """
        Get summary metrics for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing the run's final summary metrics.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}/{run_id}/summary",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
