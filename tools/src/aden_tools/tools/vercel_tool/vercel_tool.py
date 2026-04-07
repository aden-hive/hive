"""
Vercel Tool - Deployment and hosting management via Vercel REST API.

Supports:
- Vercel access token (VERCEL_TOKEN)
- Deployment listing and management
- Project management
- Domain management
- Environment variable management

API Reference: https://vercel.com/docs/rest-api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

VERCEL_API = "https://api.vercel.com"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("vercel")
    return os.getenv("VERCEL_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{VERCEL_API}/{endpoint}", headers=_headers(token), params=params, timeout=30.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your VERCEL_TOKEN."}
        if resp.status_code == 403:
            return {"error": f"Forbidden: {resp.text[:300]}"}
        if resp.status_code != 200:
            return {"error": f"Vercel API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Vercel timed out"}
    except Exception as e:
        return {"error": f"Vercel request failed: {e!s}"}


def _post(endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{VERCEL_API}/{endpoint}", headers=_headers(token), json=body or {}, timeout=30.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your VERCEL_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Vercel API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Vercel timed out"}
    except Exception as e:
        return {"error": f"Vercel request failed: {e!s}"}


def _delete(endpoint: str, token: str) -> dict[str, Any]:
    try:
        resp = httpx.delete(f"{VERCEL_API}/{endpoint}", headers=_headers(token), timeout=30.0)
        if resp.status_code not in (200, 204):
            return {"error": f"Vercel API error {resp.status_code}: {resp.text[:500]}"}
        return {"status": "deleted"}
    except Exception as e:
        return {"error": f"Vercel request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "VERCEL_TOKEN not set",
        "help": "Get a token at https://vercel.com/account/tokens",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Vercel tools with the MCP server."""

    # ── Deployments ─────────────────────────────────────────────

    @mcp.tool()
    def vercel_list_deployments(
        project_id: str = "",
        limit: int = 20,
        state: str = "",
    ) -> dict[str, Any]:
        """
        List Vercel deployments, optionally filtered by project.

        Args:
            project_id: Filter by project ID or name (optional)
            limit: Number of deployments to return (1-100, default 20)
            state: Filter by state: BUILDING, ERROR, INITIALIZING, QUEUED, READY, CANCELED
        Returns:
            Dict with deployments list (uid, name, url, state, created, target)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if project_id:
            params["projectId"] = project_id
        if state:
            params["state"] = state

        data = _get("v6/deployments", token, params)
        if "error" in data:
            return data

        deployments = []
        for d in data.get("deployments", []):
            deployments.append(
                {
                    "uid": d.get("uid", ""),
                    "name": d.get("name", ""),
                    "url": d.get("url", ""),
                    "state": d.get("state", ""),
                    "created": d.get("created", 0),
                    "target": d.get("target", ""),
                }
            )
        return {"deployments": deployments}

    @mcp.tool()
    def vercel_get_deployment(deployment_id: str) -> dict[str, Any]:
        """
        Get details of a specific Vercel deployment.

        Args:
            deployment_id: Deployment UID or URL

        Returns:
            Dict with deployment details: uid, name, url, state, target,
            created, buildingAt, ready, creator, meta
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not deployment_id:
            return {"error": "deployment_id is required"}

        data = _get(f"v13/deployments/{deployment_id}", token)
        if "error" in data:
            return data
        return {
            "uid": data.get("id", ""),
            "name": data.get("name", ""),
            "url": data.get("url", ""),
            "state": data.get("readyState", ""),
            "target": data.get("target", ""),
            "created": data.get("createdAt", 0),
            "ready": data.get("ready", 0),
            "creator": data.get("creator", {}).get("username", ""),
            "meta": data.get("meta", {}),
        }

    # ── Projects ────────────────────────────────────────────────

    @mcp.tool()
    def vercel_list_projects(limit: int = 20) -> dict[str, Any]:
        """
        List all Vercel projects.

        Args:
            limit: Number of projects to return (1-100, default 20)

        Returns:
            Dict with projects list (id, name, framework, updatedAt, latestDeploymentUrl)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        params = {"limit": max(1, min(limit, 100))}
        data = _get("v9/projects", token, params)
        if "error" in data:
            return data

        projects = []
        for p in data.get("projects", []):
            latest = p.get("latestDeployments", [{}])
            latest_url = latest[0].get("url", "") if latest else ""
            projects.append(
                {
                    "id": p.get("id", ""),
                    "name": p.get("name", ""),
                    "framework": p.get("framework", ""),
                    "updatedAt": p.get("updatedAt", 0),
                    "latestDeploymentUrl": latest_url,
                }
            )
        return {"projects": projects}

    @mcp.tool()
    def vercel_get_project(project_id: str) -> dict[str, Any]:
        """
        Get details of a Vercel project.

        Args:
            project_id: Project ID or name

        Returns:
            Dict with project details: id, name, framework, nodeVersion, targets, env vars count
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        data = _get(f"v9/projects/{project_id}", token)
        if "error" in data:
            return data
        return {
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "framework": data.get("framework", ""),
            "nodeVersion": data.get("nodeVersion", ""),
            "updatedAt": data.get("updatedAt", 0),
            "env_count": len(data.get("env", [])),
        }

    # ── Domains ─────────────────────────────────────────────────

    @mcp.tool()
    def vercel_list_project_domains(project_id: str) -> dict[str, Any]:
        """
        List domains configured for a Vercel project.

        Args:
            project_id: Project ID or name

        Returns:
            Dict with domains list (name, redirect, gitBranch, verified)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        data = _get(f"v9/projects/{project_id}/domains", token)
        if "error" in data:
            return data

        domains = []
        for d in data.get("domains", []):
            domains.append(
                {
                    "name": d.get("name", ""),
                    "redirect": d.get("redirect", ""),
                    "gitBranch": d.get("gitBranch", ""),
                    "verified": d.get("verified", False),
                }
            )
        return {"project_id": project_id, "domains": domains}

    # ── Environment Variables ───────────────────────────────────

    @mcp.tool()
    def vercel_list_env_vars(project_id: str) -> dict[str, Any]:
        """
        List environment variables for a Vercel project.

        Args:
            project_id: Project ID or name

        Returns:
            Dict with env vars list (key, target, type). Values are NOT returned for security.
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not project_id:
            return {"error": "project_id is required"}

        data = _get(f"v9/projects/{project_id}/env", token)
        if "error" in data:
            return data

        env_vars = []
        for e in data.get("envs", []):
            env_vars.append(
                {
                    "id": e.get("id", ""),
                    "key": e.get("key", ""),
                    "target": e.get("target", []),
                    "type": e.get("type", ""),
                }
            )
        return {"project_id": project_id, "env_vars": env_vars}

    @mcp.tool()
    def vercel_create_env_var(
        project_id: str,
        key: str,
        value: str,
        target: str = "production,preview,development",
        env_type: str = "encrypted",
    ) -> dict[str, Any]:
        """
        Create an environment variable for a Vercel project.

        Args:
            project_id: Project ID or name
            key: Environment variable name
            value: Environment variable value
            target: Comma-separated targets: production, preview, development
            env_type: Type: encrypted, plain, sensitive, system (default encrypted)

        Returns:
            Dict with created env var id and key
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not project_id or not key or not value:
            return {"error": "project_id, key, and value are required"}

        targets = [t.strip() for t in target.split(",") if t.strip()]
        body = {"key": key, "value": value, "target": targets, "type": env_type}
        data = _post(f"v10/projects/{project_id}/env", token, body)
        if "error" in data:
            return data
        return {"id": data.get("id", ""), "key": key, "status": "created"}
