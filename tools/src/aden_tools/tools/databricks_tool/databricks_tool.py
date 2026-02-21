"""
Databricks Tool - Interact with Databricks workspace, SQL warehouses, and jobs.

Supports:
- Execute SQL queries on SQL Warehouses
- Trigger and monitor Databricks jobs
- Explore Unity Catalog (tables, schemas, catalogs)
- Browse workspace notebooks and folders

API Reference: https://docs.databricks.com/api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _DatabricksClient:
    """Internal client wrapping Databricks REST API calls."""

    def __init__(self, host: str, token: str):
        self._host = host.rstrip("/")
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Databricks API response."""
        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_msg = error_data.get("message", response.text)
            except Exception:
                error_msg = response.text
            return {"error": f"HTTP {response.status_code}: {error_msg}"}
        try:
            return response.json()
        except Exception:
            return {"success": True, "raw_response": response.text}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the Databricks API."""
        response = httpx.get(
            f"{self._host}{path}",
            headers=self._headers,
            params=params,
            timeout=60.0,
        )
        return self._handle_response(response)

    def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a POST request to the Databricks API."""
        response = httpx.post(
            f"{self._host}{path}",
            headers=self._headers,
            json=body or {},
            timeout=60.0,
        )
        return self._handle_response(response)

    def execute_sql(
        self,
        warehouse_id: str,
        query: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Execute a SQL statement on a SQL Warehouse."""
        body: dict[str, Any] = {
            "warehouse_id": warehouse_id,
            "statement": query,
        }
        if catalog:
            body["catalog"] = catalog
        if schema:
            body["schema"] = schema
        return self._post("/api/2.0/sql/statements", body)

    def get_statement_status(self, statement_id: str) -> dict[str, Any]:
        """Get the status of a SQL statement execution."""
        return self._get(f"/api/2.0/sql/statements/{statement_id}")

    def cancel_statement(self, statement_id: str) -> dict[str, Any]:
        """Cancel a running SQL statement."""
        return self._post(f"/api/2.0/sql/statements/{statement_id}/cancel")

    def list_warehouses(self) -> dict[str, Any]:
        """List all SQL warehouses."""
        return self._get("/api/2.0/sql/warehouses")

    def list_jobs(self, limit: int = 20, name: str | None = None) -> dict[str, Any]:
        """List Databricks jobs."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if name:
            params["name"] = name
        return self._get("/api/2.1/jobs/list", params)

    def get_job(self, job_id: int) -> dict[str, Any]:
        """Get details of a specific job."""
        return self._get("/api/2.1/jobs/get", {"job_id": job_id})

    def run_job(
        self,
        job_id: int,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a Databricks job run."""
        body: dict[str, Any] = {"job_id": job_id}
        if parameters:
            body["notebook_params"] = parameters
        return self._post("/api/2.1/jobs/run-now", body)

    def get_run_status(self, run_id: int) -> dict[str, Any]:
        """Get the status of a job run."""
        return self._get("/api/2.1/jobs/runs/get", {"run_id": run_id})

    def cancel_run(self, run_id: int) -> dict[str, Any]:
        """Cancel a job run."""
        return self._post("/api/2.1/jobs/runs/cancel", {"run_id": run_id})

    def list_workspace(self, path: str = "/") -> dict[str, Any]:
        """List contents of a workspace path (notebooks, directories)."""
        return self._get("/api/2.0/workspace/list", {"path": path})

    def get_status(self, path: str) -> dict[str, Any]:
        """Get the status of a workspace object."""
        return self._get("/api/2.0/workspace/get-status", {"path": path})

    def export_notebook(self, path: str, format: str = "SOURCE") -> dict[str, Any]:
        """Export a notebook's content."""
        return self._get("/api/2.0/workspace/export", {"path": path, "format": format})

    def list_catalogs(self) -> dict[str, Any]:
        """List all catalogs in Unity Catalog."""
        return self._get("/api/2.1/unity-catalog/catalogs")

    def get_catalog(self, name: str) -> dict[str, Any]:
        """Get details of a specific catalog."""
        return self._get(f"/api/2.1/unity-catalog/catalogs/{name}")

    def list_schemas(self, catalog_name: str) -> dict[str, Any]:
        """List schemas in a catalog."""
        return self._get("/api/2.1/unity-catalog/schemas", {"catalog_name": catalog_name})

    def get_schema(self, full_name: str) -> dict[str, Any]:
        """Get details of a specific schema."""
        return self._get(f"/api/2.1/unity-catalog/schemas/{full_name}")

    def list_tables(self, catalog_name: str, schema_name: str) -> dict[str, Any]:
        """List tables in a schema."""
        return self._get(
            "/api/2.1/unity-catalog/tables",
            {"catalog_name": catalog_name, "schema_name": schema_name},
        )

    def get_table(self, full_name: str) -> dict[str, Any]:
        """Get details of a specific table (including schema/columns)."""
        return self._get(f"/api/2.1/unity-catalog/tables/{full_name}")

    def list_functions(self, catalog_name: str, schema_name: str) -> dict[str, Any]:
        """List functions in a schema."""
        return self._get(
            "/api/2.1/unity-catalog/functions",
            {"catalog_name": catalog_name, "schema_name": schema_name},
        )


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Databricks tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Databricks token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("databricks")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('databricks'), got {type(token).__name__}"
                )
            return token
        return os.getenv("DATABRICKS_TOKEN")

    def _get_host() -> str | None:
        """Get Databricks host from credential manager or environment."""
        if credentials is not None:
            host = credentials.get("databricks_host")
            if host is not None and not isinstance(host, str):
                raise TypeError(
                    f"Expected string from credentials.get('databricks_host'), got {type(host).__name__}"
                )
            return host
        return os.getenv("DATABRICKS_HOST")

    def _get_client() -> _DatabricksClient | dict[str, str]:
        """Get a Databricks client, or return an error dict if no credentials."""
        token = _get_token()
        host = _get_host()
        if not token or not host:
            return {
                "error": "Databricks credentials not configured",
                "help": "Set DATABRICKS_TOKEN and DATABRICKS_HOST environment variables",
            }
        return _DatabricksClient(host, token)

    @mcp.tool()
    def run_databricks_sql(
        query: str,
        warehouse_id: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> dict:
        """
        Execute a SQL query on a Databricks SQL Warehouse.
        The query is executed asynchronously. Use the returned statement_id to check status.

        Args:
            query: SQL query to execute (SELECT statements recommended for read-only)
            warehouse_id: ID of the SQL Warehouse to use
            catalog: Optional catalog name to use
            schema: Optional schema name to use

        Returns:
            Dict with statement_id and status, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.execute_sql(warehouse_id, query, catalog, schema)
            if "error" in result:
                return result
            return {
                "success": True,
                "statement_id": result.get("statement_id"),
                "status": result.get("status", {}).get("state"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_get_statement_status(statement_id: str) -> dict:
        """
        Get the status and results of a SQL statement execution.

        Args:
            statement_id: ID of the SQL statement from run_databricks_sql

        Returns:
            Dict with statement status and results (if complete)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_statement_status(statement_id)
            if "error" in result:
                return result
            status = result.get("status", {})
            response: dict[str, Any] = {
                "success": True,
                "statement_id": statement_id,
                "state": status.get("state"),
            }
            if result.get("result"):
                response["result"] = result.get("result")
            if status.get("error"):
                response["error"] = status.get("error")
            return response
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def trigger_databricks_job(
        job_id: int,
        parameters: dict[str, Any] | None = None,
    ) -> dict:
        """
        Trigger a Databricks job to run.

        Args:
            job_id: ID of the job to trigger
            parameters: Optional dictionary of parameters to pass to the job

        Returns:
            Dict with run_id and initial status, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.run_job(job_id, parameters)
            if "error" in result:
                return result
            return {
                "success": True,
                "run_id": result.get("run_id"),
                "number_in_job": result.get("number_in_job"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_get_job_status(run_id: int) -> dict:
        """
        Get the status of a Databricks job run.

        Args:
            run_id: ID of the job run (from trigger_databricks_job)

        Returns:
            Dict with job run status and details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_run_status(run_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "run_id": run_id,
                "state": result.get("state", {}).get("life_cycle_state"),
                "result_state": result.get("state", {}).get("result_state"),
                "state_message": result.get("state", {}).get("state_message"),
                "start_time": result.get("start_time"),
                "end_time": result.get("end_time"),
                "run_duration": result.get("run_duration"),
                "run_page_url": result.get("run_page_url"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def describe_table(full_name: str) -> dict:
        """
        Get schema and metadata for a table in Unity Catalog.

        Args:
            full_name: Full table name (catalog.schema.table)

        Returns:
            Dict with table schema including column names, types, and comments
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_table(full_name)
            if "error" in result:
                return result
            table_info = result
            columns = [
                {
                    "name": col.get("name"),
                    "type_text": col.get("type_text"),
                    "type_name": col.get("type_name"),
                    "comment": col.get("comment"),
                    "nullable": col.get("nullable", True),
                }
                for col in table_info.get("columns", [])
            ]
            return {
                "success": True,
                "name": table_info.get("name"),
                "full_name": table_info.get("full_name"),
                "catalog_name": table_info.get("catalog_name"),
                "schema_name": table_info.get("schema_name"),
                "table_type": table_info.get("table_type"),
                "data_source_format": table_info.get("data_source_format"),
                "comment": table_info.get("comment"),
                "columns": columns,
                "owner": table_info.get("owner"),
                "created_at": table_info.get("created_at"),
                "updated_at": table_info.get("updated_at"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def list_workspace(path: str = "/") -> dict:
        """
        List notebooks and folders in a Databricks workspace path.

        Args:
            path: Workspace path to list (default: root "/")

        Returns:
            Dict with list of objects (notebooks, directories, files)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_workspace(path)
            if "error" in result:
                return result
            objects = result.get("objects", [])
            items = [
                {
                    "path": obj.get("path"),
                    "object_type": obj.get("object_type"),
                    "object_id": obj.get("object_id"),
                }
                for obj in objects
            ]
            return {
                "success": True,
                "path": path,
                "objects": items,
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_list_warehouses() -> dict:
        """
        List all SQL Warehouses in the Databricks workspace.

        Returns:
            Dict with list of SQL warehouses
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_warehouses()
            if "error" in result:
                return result
            warehouses = result.get("warehouses", [])
            items = [
                {
                    "id": wh.get("id"),
                    "name": wh.get("name"),
                    "size": wh.get("size"),
                    "state": wh.get("state"),
                    "auto_stop_min": wh.get("auto_stop_mins"),
                    "spot_instance_policy": wh.get("spot_instance_policy"),
                    "enable_serverless_compute": wh.get("enable_serverless_compute"),
                }
                for wh in warehouses
            ]
            return {
                "success": True,
                "warehouses": items,
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_list_jobs(limit: int = 20, name: str | None = None) -> dict:
        """
        List Databricks jobs in the workspace.

        Args:
            limit: Maximum number of jobs to return (1-100)
            name: Optional filter by job name

        Returns:
            Dict with list of jobs
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_jobs(limit, name)
            if "error" in result:
                return result
            jobs = result.get("jobs", [])
            items = [
                {
                    "job_id": job.get("job_id"),
                    "settings": job.get("settings", {}),
                    "created_time": job.get("created_time"),
                    "creator_user_name": job.get("creator_user_name"),
                }
                for job in jobs
            ]
            return {
                "success": True,
                "jobs": items,
                "count": len(items),
                "has_more": result.get("has_more", False),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_list_catalogs() -> dict:
        """
        List all catalogs in Unity Catalog.

        Returns:
            Dict with list of catalogs
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_catalogs()
            if "error" in result:
                return result
            catalogs = result.get("catalogs", [])
            items = [
                {
                    "name": cat.get("name"),
                    "comment": cat.get("comment"),
                    "owner": cat.get("owner"),
                    "metastore_id": cat.get("metastore_id"),
                    "created_at": cat.get("created_at"),
                }
                for cat in catalogs
            ]
            return {
                "success": True,
                "catalogs": items,
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_list_schemas(catalog_name: str) -> dict:
        """
        List schemas in a Unity Catalog catalog.

        Args:
            catalog_name: Name of the catalog

        Returns:
            Dict with list of schemas
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_schemas(catalog_name)
            if "error" in result:
                return result
            schemas = result.get("schemas", [])
            items = [
                {
                    "name": schema.get("name"),
                    "full_name": schema.get("full_name"),
                    "comment": schema.get("comment"),
                    "owner": schema.get("owner"),
                    "created_at": schema.get("created_at"),
                }
                for schema in schemas
            ]
            return {
                "success": True,
                "catalog_name": catalog_name,
                "schemas": items,
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def databricks_list_tables(catalog_name: str, schema_name: str) -> dict:
        """
        List tables in a Unity Catalog schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema

        Returns:
            Dict with list of tables
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_tables(catalog_name, schema_name)
            if "error" in result:
                return result
            tables = result.get("tables", [])
            items = [
                {
                    "name": tbl.get("name"),
                    "full_name": tbl.get("full_name"),
                    "table_type": tbl.get("table_type"),
                    "data_source_format": tbl.get("data_source_format"),
                    "comment": tbl.get("comment"),
                    "owner": tbl.get("owner"),
                    "created_at": tbl.get("created_at"),
                }
                for tbl in tables
            ]
            return {
                "success": True,
                "catalog_name": catalog_name,
                "schema_name": schema_name,
                "tables": items,
                "count": len(items),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
