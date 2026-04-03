"""
Weights & Biases integration tool for experiment tracking and model monitoring.

Supports:
- HTTP Bearer Auth with WANDB_API_KEY.
- Cloud (api.wandb.ai) and self-hosted instances.

API Reference: https://api.wandb.ai/api/v1/
"""

from __future__ import annotations

import os
from json import JSONDecodeError
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
        try:
            api_key = credentials.get("wandb_api_key") or os.getenv("WANDB_API_KEY")
            host = credentials.get("wandb_host") or os.getenv("WANDB_HOST") or DEFAULT_HOST
        except KeyError:
            api_key = os.getenv("WANDB_API_KEY")
            host = os.getenv("WANDB_HOST") or DEFAULT_HOST
    else:
        api_key = os.getenv("WANDB_API_KEY")
        host = os.getenv("WANDB_HOST") or DEFAULT_HOST

    if not api_key:
        return {
            "error": "Weights & Biases credentials not configured",
            "help": (
                "Set WANDB_API_KEY environment variable or configure via "
                "credential store"
            ),
        }
    host = host.rstrip("/")
    return api_key, host


def _auth_header(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


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
        except (ValueError, JSONDecodeError):
            detail = resp.text
        return {"error": f"Weights & Biases API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Weights & Biases experiment tracking tools with the MCP server."""

    @mcp.tool()
    def wandb_list_projects(entity: str) -> dict[str, Any]:
        """
        List projects from Weights & Biases for a given entity (username or org).

        Args:
            entity: The entity name (username or organization).

        Returns:
            Dict containing projects list.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/projects/{entity}",
                headers=_auth_header(api_key),
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_list_runs(entity: str, project: str, per_page: int = 50) -> dict[str, Any]:
        """
        List runs in a project from Weights & Biases.

        Args:
            entity: The entity name.
            project: The project name.
            per_page: Number of runs to return (default 50, max 1000).

        Returns:
            Dict containing runs list.
        """
        if per_page < 1 or per_page > 1000:
            return {"error": "per_page must be between 1 and 1000"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            params = {"per_page": per_page}
            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}",
                headers=_auth_header(api_key),
                params=params,
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_get_run(entity: str, project: str, run_id: str) -> dict[str, Any]:
        """
        Get details of a specific Weights & Biases run.

        Args:
            entity: The entity name.
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing run details.
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
                headers=_auth_header(api_key),
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_get_run_metrics(entity: str, project: str, run_id: str) -> dict[str, Any]:
        """
        Get metrics history for a specific Weights & Biases run.

        Args:
            entity: The entity name.
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing metric history.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/runs/{entity}/{project}/{run_id}/history",
                headers=_auth_header(api_key),
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def wandb_list_artifacts(entity: str, project: str) -> dict[str, Any]:
        """
        List artifacts in a Weights & Biases project.

        Args:
            entity: The entity name.
            project: The project name.

        Returns:
            Dict containing artifacts list.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, host = creds

        try:
            resp = httpx.get(
                f"{host}/api/v1/artifacts/{entity}/{project}",
                headers=_auth_header(api_key),
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
