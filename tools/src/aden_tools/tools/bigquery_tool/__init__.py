"""
BigQuery Tool - Query and explore Google BigQuery datasets.

Provides MCP tools for executing SQL queries and exploring dataset schemas.
"""

from .bigquery_tool import register_tools

__all__ = ["register_tools"]
