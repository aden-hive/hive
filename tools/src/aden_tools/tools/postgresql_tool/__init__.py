"""
PostgreSQL Tool - Execute SQL queries and transactions against PostgreSQL.

Provides MCP tools for operational database workflows including
read-only queries, transactions, schema inspection, and health checks.
"""

from .postgresql_tool import register_tools

__all__ = ["register_tools"]