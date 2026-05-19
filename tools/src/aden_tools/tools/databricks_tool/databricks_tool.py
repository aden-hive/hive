"""
Databricks Tool - Workspace, SQL statement execution, and job management.

Supports:
- Databricks personal access token (DATABRICKS_TOKEN) + host URL (DATABRICKS_HOST)
- SQL statement execution via SQL Warehouses
- Job listing, running, and status tracking
- Cluster management (list, get, start, terminate)

API Reference: https://docs.databricks.com/api/workspace/introduction
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_config(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (token, host)."""
    if credentials is not None:
        token = credentials.get("databricks")
    else:
        token = os.getenv("DATABRICKS_TOKEN")
    host = os.getenv("DATABRICKS_HOST", "")
    return token, host.rstrip("/") if host else None


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(host: str, endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{host}/api/2.0/{endpoint}", headers=_headers(token), params=params, timeout=30.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your DATABRICKS_TOKEN."}
        if resp.status_code == 403:
            return {"error": f"Forbidden: {resp.text[:300]}"}
        if resp.status_code != 200:
            return {"error": f"Databricks API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Databricks timed out"}
    except Exception as e:
        return {"error": f"Databricks request failed: {e!s}"}


def _post(host: str, endpoint: str, token: str, body: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{host}/api/2.0/{endpoint}", headers=_headers(token), json=body or {}, timeout=60.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your DATABRICKS_TOKEN."}
        if resp.status_code not in (200, 201):
            return {"error": f"Databricks API error {resp.status_code}: {resp.text[:500]}"}
        if not resp.text:
            return {"status": "success"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Databricks timed out"}
    except Exception as e:
        return {"error": f"Databricks request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "DATABRICKS_TOKEN or DATABRICKS_HOST not set",
        "help": (
            "Set DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
            " and DATABRICKS_TOKEN=dapi..."
        ),
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Databricks tools with the MCP server."""

    # ── SQL Statement Execution ─────────────────────────────────

    @mcp.tool()
    def databricks_sql_query(
        statement: str,
        warehouse_id: str,
        max_rows: int = 100,
    ) -> dict[str, Any]:
        """
        Execute a SQL statement on a Databricks SQL Warehouse.

        Args:
            statement: SQL query to execute
            warehouse_id: SQL warehouse ID to run the query on
            max_rows: Maximum rows to return (default 100)

        Returns:
            Dict with status, columns list, rows (as list of lists), and row_count
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()
        if not statement or not warehouse_id:
            return {"error": "statement and warehouse_id are required"}

        body = {
            "statement": statement,
            "warehouse_id": warehouse_id,
            "wait_timeout": "30s",
            "row_limit": max(1, min(max_rows, 10000)),
        }
        data = _post(host, "sql/statements", token, body)
        if "error" in data:
            return data

        status = data.get("status", {}).get("state", "UNKNOWN")
        if status == "FAILED":
            msg = data.get("status", {}).get("error", {}).get("message", "Query failed")
            return {"error": f"SQL query failed: {msg}"}

        manifest = data.get("manifest", {})
        columns = [col.get("name", "") for col in manifest.get("schema", {}).get("columns", [])]
        result_data = data.get("result", {}).get("data_array", [])

        return {
            "status": status,
            "columns": columns,
            "rows": result_data,
            "row_count": len(result_data),
            "statement_id": data.get("statement_id", ""),
        }

    # ── Jobs ────────────────────────────────────────────────────

    @mcp.tool()
    def databricks_list_jobs(
        max_results: int = 25,
        name_filter: str = "",
    ) -> dict[str, Any]:
        """
        List jobs in the Databricks workspace.

        Args:
            max_results: Number of jobs to return (1-100, default 25)
            name_filter: Filter jobs by name substring

        Returns:
            Dict with jobs list (job_id, name, creator, created_time)
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()

        params: dict[str, Any] = {"limit": max(1, min(max_results, 100))}
        if name_filter:
            params["name"] = name_filter

        data = _get(host, "jobs/list", token, params)
        if "error" in data:
            return data

        jobs = []
        for job in data.get("jobs", []):
            settings = job.get("settings", {})
            jobs.append(
                {
                    "job_id": job.get("job_id", 0),
                    "name": settings.get("name", ""),
                    "creator": job.get("creator_user_name", ""),
                    "created_time": job.get("created_time", 0),
                }
            )
        return {"jobs": jobs}

    @mcp.tool()
    def databricks_run_job(
        job_id: int,
    ) -> dict[str, Any]:
        """
        Trigger a job run in Databricks.

        Args:
            job_id: The ID of the job to run

        Returns:
            Dict with run_id for tracking the job execution
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()
        if not job_id:
            return {"error": "job_id is required"}

        data = _post(host, "jobs/run-now", token, {"job_id": job_id})
        if "error" in data:
            return data
        return {"run_id": data.get("run_id", 0), "job_id": job_id, "status": "triggered"}

    @mcp.tool()
    def databricks_get_run(run_id: int) -> dict[str, Any]:
        """
        Get the status of a Databricks job run.

        Args:
            run_id: The run ID from databricks_run_job

        Returns:
            Dict with run_id, job_id, state, start_time, and result_state
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()
        if not run_id:
            return {"error": "run_id is required"}

        data = _get(host, "jobs/runs/get", token, {"run_id": run_id})
        if "error" in data:
            return data

        state = data.get("state", {})
        return {
            "run_id": data.get("run_id", 0),
            "job_id": data.get("job_id", 0),
            "state": state.get("life_cycle_state", ""),
            "result_state": state.get("result_state", ""),
            "start_time": data.get("start_time", 0),
            "run_page_url": data.get("run_page_url", ""),
        }

    # ── Clusters ────────────────────────────────────────────────

    @mcp.tool()
    def databricks_list_clusters() -> dict[str, Any]:
        """
        List all clusters in the Databricks workspace.

        Returns:
            Dict with clusters list (cluster_id, cluster_name, state, spark_version, creator)
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()

        data = _get(host, "clusters/list", token)
        if "error" in data:
            return data

        clusters = []
        for c in data.get("clusters", []):
            clusters.append(
                {
                    "cluster_id": c.get("cluster_id", ""),
                    "cluster_name": c.get("cluster_name", ""),
                    "state": c.get("state", ""),
                    "spark_version": c.get("spark_version", ""),
                    "creator": c.get("creator_user_name", ""),
                    "num_workers": c.get("num_workers", 0),
                }
            )
        return {"clusters": clusters}

    @mcp.tool()
    def databricks_start_cluster(cluster_id: str) -> dict[str, Any]:
        """
        Start a terminated Databricks cluster.

        Args:
            cluster_id: The cluster ID to start

        Returns:
            Dict with status confirmation
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()
        if not cluster_id:
            return {"error": "cluster_id is required"}

        data = _post(host, "clusters/start", token, {"cluster_id": cluster_id})
        if "error" in data:
            return data
        return {"status": "starting", "cluster_id": cluster_id}

    @mcp.tool()
    def databricks_terminate_cluster(cluster_id: str) -> dict[str, Any]:
        """
        Terminate a running Databricks cluster.

        Args:
            cluster_id: The cluster ID to terminate

        Returns:
            Dict with status confirmation
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()
        if not cluster_id:
            return {"error": "cluster_id is required"}

        data = _post(host, "clusters/delete", token, {"cluster_id": cluster_id})
        if "error" in data:
            return data
        return {"status": "terminating", "cluster_id": cluster_id}

    # ── Workspace ───────────────────────────────────────────────

    @mcp.tool()
    def databricks_list_workspace(path: str = "/") -> dict[str, Any]:
        """
        List objects in a Databricks workspace directory.

        Args:
            path: Workspace path to list (default "/" for root)

        Returns:
            Dict with path and objects list (path, object_type, language)
        """
        token, host = _get_config(credentials)
        if not token or not host:
            return _auth_error()

        data = _get(host, "workspace/list", token, {"path": path})
        if "error" in data:
            return data

        objects = []
        for obj in data.get("objects", []):
            objects.append(
                {
                    "path": obj.get("path", ""),
                    "object_type": obj.get("object_type", ""),
                    "language": obj.get("language", ""),
                }
            )
        return {"path": path, "objects": objects}
