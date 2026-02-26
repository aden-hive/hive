"""
Databricks Tool - Query Databricks SQL Warehouses and interact with managed MCP servers.

Provides MCP tools for:
- Executing read-only SQL queries via Databricks SQL Warehouses
- Describing tables via Unity Catalog
- Interacting with Databricks managed MCP servers (SQL, Vector Search, Genie, UC functions)
"""

from .databricks_tool import register_tools

__all__ = ["register_tools"]
