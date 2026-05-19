"""
Databricks Managed MCP Server Tools.

Provides tools to interact with Databricks managed MCP server endpoints:
- SQL: Execute queries via the managed SQL MCP server
- Unity Catalog Functions: Execute predefined UC functions
- Vector Search: Query Vector Search indexes
- Genie: Query Genie spaces with natural language
- Discovery: List available tools on any managed MCP server

These tools use the official databricks-mcp library for authentication
and communication with Databricks managed MCP server endpoints.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)


def _get_mcp_client(server_url: str, host: str | None, token: str | None) -> Any:
    """
    Create a DatabricksMCPClient for the given server URL.

    Args:
        server_url: Full URL of the managed MCP server endpoint
        host: Databricks workspace URL
        token: Personal access token

    Returns:
        DatabricksMCPClient instance

    Raises:
        ImportError: If databricks-mcp or databricks-sdk is not installed
    """
    try:
        from databricks.sdk import WorkspaceClient
        from databricks_mcp import DatabricksMCPClient
    except ImportError:
        raise ImportError(
            "databricks-mcp and databricks-sdk are required for Databricks MCP tools. "
            "Install them with: pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'"
        ) from None

    kwargs: dict[str, str] = {}
    if host:
        kwargs["host"] = host
    if token:
        kwargs["token"] = token

    workspace_client = WorkspaceClient(**kwargs)
    return DatabricksMCPClient(server_url=server_url, workspace_client=workspace_client)


def register_mcp_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Databricks managed MCP server tools with the MCP server."""

    def _get_credentials() -> dict[str, str | None]:
        """Get Databricks credentials from credential store or environment."""
        if credentials is not None:
            try:
                host = credentials.get("databricks_host")
            except KeyError:
                host = None
            try:
                token = credentials.get("databricks_token")
            except KeyError:
                token = None
            try:
                warehouse = credentials.get("databricks_warehouse")
            except KeyError:
                warehouse = None
            return {
                "host": host,
                "token": token,
                "warehouse_id": warehouse,
            }
        return {
            "host": os.getenv("DATABRICKS_HOST"),
            "token": os.getenv("DATABRICKS_TOKEN"),
            "warehouse_id": os.getenv("DATABRICKS_WAREHOUSE_ID"),
        }

    def _get_host() -> str | None:
        """Get the Databricks workspace host URL."""
        creds = _get_credentials()
        return creds.get("host")

    def _build_server_url(path: str) -> str | None:
        """Build a full managed MCP server URL from a path suffix."""
        host = _get_host()
        if not host:
            return None
        # Ensure host doesn't have trailing slash
        host = host.rstrip("/")
        return f"{host}{path}"

    @mcp.tool()
    def databricks_mcp_query_sql(
        sql: str,
        warehouse_id: str | None = None,
    ) -> dict:
        """
        Execute a SQL query via the Databricks managed SQL MCP server.

        Unlike run_databricks_sql, this tool uses the official Databricks managed
        MCP SQL server endpoint and supports both read and write operations as
        permitted by the workspace.

        Args:
            sql: The SQL query to execute.
            warehouse_id: SQL Warehouse ID. Falls back to DATABRICKS_WAREHOUSE_ID
                         env var if not provided. Required for the SQL MCP server.

        Returns:
            Dict with query results:
            - success: True if query executed successfully
            - result: The query result text from the MCP server

            Or error dict with:
            - error: Error message
            - help: Optional help text

        Example:
            >>> databricks_mcp_query_sql("SELECT * FROM main.default.users LIMIT 10")
            {
                "success": True,
                "result": "..."
            }
        """
        if not sql or not sql.strip():
            return {"error": "sql is required"}

        try:
            creds = _get_credentials()
            server_url = _build_server_url("/api/2.0/mcp/sql")

            if not server_url:
                return {
                    "error": "Databricks host not configured",
                    "help": "Set DATABRICKS_HOST environment variable to your workspace URL.",
                }

            effective_warehouse = warehouse_id or creds.get("warehouse_id")
            mcp_client = _get_mcp_client(
                server_url=server_url,
                host=creds.get("host"),
                token=creds.get("token"),
            )

            # Build arguments for the SQL tool
            tool_args: dict[str, Any] = {"statement": sql}
            if effective_warehouse:
                tool_args["warehouse_id"] = effective_warehouse

            response = mcp_client.call_tool("execute_sql", tool_args)
            result_text = "".join([c.text for c in response.content])

            return {
                "success": True,
                "result": result_text,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: "
                "pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            return {"error": f"Databricks MCP SQL query failed: {e!s}"}

    @mcp.tool()
    def databricks_mcp_query_uc_function(
        catalog: str,
        schema: str,
        function_name: str,
        arguments: dict | None = None,
    ) -> dict:
        """
        Execute a Unity Catalog function via the Databricks managed MCP server.

        Use this to run predefined SQL functions registered in Unity Catalog.
        These functions encapsulate business logic and can be invoked as tools.

        Args:
            catalog: Unity Catalog catalog name (e.g., "main").
            schema: Schema name within the catalog (e.g., "default").
            function_name: Name of the UC function to execute.
            arguments: Optional dict of arguments to pass to the function.

        Returns:
            Dict with function result:
            - success: True if function executed successfully
            - result: The function result text from the MCP server

            Or error dict with:
            - error: Error message

        Example:
            >>> databricks_mcp_query_uc_function(
            ...     catalog="main",
            ...     schema="analytics",
            ...     function_name="get_revenue_summary",
            ...     arguments={"start_date": "2024-01-01", "end_date": "2024-12-31"}
            ... )
            {
                "success": True,
                "result": "Revenue summary: ..."
            }
        """
        if not catalog or not catalog.strip():
            return {"error": "catalog is required"}
        if not schema or not schema.strip():
            return {"error": "schema is required"}
        if not function_name or not function_name.strip():
            return {"error": "function_name is required"}

        try:
            creds = _get_credentials()
            path = f"/api/2.0/mcp/functions/{catalog}/{schema}/{function_name}"
            server_url = _build_server_url(path)

            if not server_url:
                return {
                    "error": "Databricks host not configured",
                    "help": "Set DATABRICKS_HOST environment variable.",
                }

            mcp_client = _get_mcp_client(
                server_url=server_url,
                host=creds.get("host"),
                token=creds.get("token"),
            )

            # Construct the tool name using the UC naming convention
            tool_name = f"{catalog}__{schema}__{function_name}"
            tool_args = arguments or {}

            response = mcp_client.call_tool(tool_name, tool_args)
            result_text = "".join([c.text for c in response.content])

            return {
                "success": True,
                "result": result_text,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: "
                "pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            return {"error": f"Databricks UC function call failed: {e!s}"}

    @mcp.tool()
    def databricks_mcp_vector_search(
        catalog: str,
        schema: str,
        index_name: str,
        query: str,
        num_results: int = 10,
    ) -> dict:
        """
        Query a Databricks Vector Search index via the managed MCP server.

        Use this to find semantically relevant documents from a Vector Search
        index that uses Databricks managed embeddings.

        Args:
            catalog: Unity Catalog catalog name containing the index.
            schema: Schema name within the catalog.
            index_name: Name of the Vector Search index.
            query: The search query text.
            num_results: Number of results to return (default: 10).

        Returns:
            Dict with search results:
            - success: True if search executed successfully
            - result: The search result text from the MCP server

            Or error dict with:
            - error: Error message

        Example:
            >>> databricks_mcp_vector_search(
            ...     catalog="prod",
            ...     schema="knowledge_base",
            ...     index_name="docs_index",
            ...     query="How to configure authentication?",
            ...     num_results=5
            ... )
            {
                "success": True,
                "result": "..."
            }
        """
        if not catalog or not catalog.strip():
            return {"error": "catalog is required"}
        if not schema or not schema.strip():
            return {"error": "schema is required"}
        if not index_name or not index_name.strip():
            return {"error": "index_name is required"}
        if not query or not query.strip():
            return {"error": "query is required"}

        try:
            creds = _get_credentials()
            path = f"/api/2.0/mcp/vector-search/{catalog}/{schema}/{index_name}"
            server_url = _build_server_url(path)

            if not server_url:
                return {
                    "error": "Databricks host not configured",
                    "help": "Set DATABRICKS_HOST environment variable.",
                }

            mcp_client = _get_mcp_client(
                server_url=server_url,
                host=creds.get("host"),
                token=creds.get("token"),
            )

            tool_args: dict[str, Any] = {
                "query": query,
                "num_results": num_results,
            }

            # Discover the actual tool name from the server
            tools = mcp_client.list_tools()
            if not tools:
                return {
                    "error": "No tools discovered on the Vector Search MCP server",
                    "help": f"Check that the index '{catalog}.{schema}.{index_name}' exists.",
                }

            tool_name = tools[0].name
            response = mcp_client.call_tool(tool_name, tool_args)
            result_text = "".join([c.text for c in response.content])

            return {
                "success": True,
                "result": result_text,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: "
                "pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            return {"error": f"Databricks Vector Search failed: {e!s}"}

    @mcp.tool()
    def databricks_mcp_query_genie(
        genie_space_id: str,
        question: str,
    ) -> dict:
        """
        Query a Databricks Genie space via the managed MCP server.

        Genie spaces allow natural language queries against structured data.
        Use this to analyze data by asking questions in plain English.
        Results are read-only.

        Note: Genie queries may take longer to execute as they involve
        natural language to SQL translation.

        Args:
            genie_space_id: The ID of the Genie space to query.
            question: Natural language question to ask the Genie space.

        Returns:
            Dict with Genie results:
            - success: True if query executed successfully
            - result: The Genie response text

            Or error dict with:
            - error: Error message

        Example:
            >>> databricks_mcp_query_genie(
            ...     genie_space_id="abc123",
            ...     question="What was the total revenue last quarter?"
            ... )
            {
                "success": True,
                "result": "The total revenue last quarter was $1.2M..."
            }
        """
        if not genie_space_id or not genie_space_id.strip():
            return {"error": "genie_space_id is required"}
        if not question or not question.strip():
            return {"error": "question is required"}

        try:
            creds = _get_credentials()
            path = f"/api/2.0/mcp/genie/{genie_space_id}"
            server_url = _build_server_url(path)

            if not server_url:
                return {
                    "error": "Databricks host not configured",
                    "help": "Set DATABRICKS_HOST environment variable.",
                }

            mcp_client = _get_mcp_client(
                server_url=server_url,
                host=creds.get("host"),
                token=creds.get("token"),
            )

            # Discover the actual tool name from the server
            tools = mcp_client.list_tools()
            if not tools:
                return {
                    "error": "No tools discovered on the Genie MCP server",
                    "help": f"Check that the Genie space '{genie_space_id}' exists "
                    "and you have access to it.",
                }

            tool_name = tools[0].name
            response = mcp_client.call_tool(tool_name, {"question": question})
            result_text = "".join([c.text for c in response.content])

            return {
                "success": True,
                "result": result_text,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: "
                "pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            return {"error": f"Databricks Genie query failed: {e!s}"}

    @mcp.tool()
    def databricks_mcp_list_tools(
        server_url: str | None = None,
        server_type: str | None = None,
        resource_path: str | None = None,
    ) -> dict:
        """
        Discover available tools on a Databricks managed MCP server.

        Use this to explore what tools are available on a specific MCP server
        endpoint before calling them. Supports both direct URL and parameterized
        server type specification.

        Args:
            server_url: Full URL of the MCP server endpoint. If provided,
                       server_type and resource_path are ignored.
            server_type: Type of managed server: "sql", "vector-search",
                        "genie", or "functions". Used with resource_path.
            resource_path: Resource path for the server type. Examples:
                          - For vector-search: "catalog/schema/index_name"
                          - For genie: "genie_space_id"
                          - For functions: "catalog/schema/function_name"
                          - For sql: not needed

        Returns:
            Dict with discovered tools:
            - success: True if discovery succeeded
            - server_url: The MCP server URL queried
            - tools: List of tool definitions (name, description, parameters)

            Or error dict with:
            - error: Error message

        Example:
            >>> databricks_mcp_list_tools(server_type="functions", resource_path="system/ai")
            {
                "success": True,
                "server_url": "https://workspace.cloud.databricks.com/api/2.0/mcp/functions/system/ai",
                "tools": [
                    {
                        "name": "system__ai__python_exec",
                        "description": "Execute Python code",
                        "parameters": {...}
                    }
                ]
            }
        """
        try:
            creds = _get_credentials()

            # Resolve server URL
            effective_url = server_url
            if not effective_url:
                if not server_type:
                    return {
                        "error": "Either server_url or server_type is required",
                        "help": "Provide a full server_url or specify server_type "
                        "(sql, vector-search, genie, functions) with resource_path.",
                    }

                valid_types = {"sql", "vector-search", "genie", "functions"}
                if server_type not in valid_types:
                    return {
                        "error": f"Invalid server_type: {server_type}",
                        "help": f"Must be one of: {', '.join(sorted(valid_types))}",
                    }

                path = f"/api/2.0/mcp/{server_type}"
                if resource_path:
                    path = f"{path}/{resource_path}"

                effective_url = _build_server_url(path)

            if not effective_url:
                return {
                    "error": "Databricks host not configured",
                    "help": "Set DATABRICKS_HOST environment variable.",
                }

            mcp_client = _get_mcp_client(
                server_url=effective_url,
                host=creds.get("host"),
                token=creds.get("token"),
            )

            tools = mcp_client.list_tools()
            tool_list = []
            for t in tools:
                tool_info: dict[str, Any] = {
                    "name": t.name,
                    "description": t.description,
                }
                if t.inputSchema:
                    tool_info["parameters"] = t.inputSchema
                tool_list.append(tool_info)

            return {
                "success": True,
                "server_url": effective_url,
                "tools": tool_list,
            }

        except ImportError as e:
            return {
                "error": str(e),
                "help": "Install dependencies: "
                "pip install 'databricks-mcp>=0.1.0' 'databricks-sdk>=0.30.0'",
            }
        except Exception as e:
            return {"error": f"Failed to list MCP tools: {e!s}"}
