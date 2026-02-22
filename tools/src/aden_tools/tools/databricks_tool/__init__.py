"""
Databricks Tool - Query and explore Databricks SQL Warehouses and Unity Catalog.

Provides MCP tools for executing SQL queries and exploring table schemas.
"""

from .databricks_tool import register_tools

__all__ = ["register_tools"]
