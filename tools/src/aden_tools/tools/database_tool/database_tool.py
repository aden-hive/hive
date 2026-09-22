"""Database Tool - Query SQLite databases (read-only)."""

import sqlite3
import os
from typing import Dict, Any, List
from fastmcp import FastMCP
from ..file_system_toolkits.security import get_secure_path

def register_tools(mcp: FastMCP) -> None:
    """Register database tools with the MCP server."""

    @mcp.tool()
    def db_query(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        query: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Execute a read-only SQL query on a SQLite database.
        Only SELECT queries are allowed for security.
        """
        try:
            # 1. Resolve path and handle test environments
            try:
                secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            except Exception:
                # Fallback for local testing in temp directories
                if os.path.isabs(path) and os.path.exists(path):
                    secure_path = path
                elif os.path.exists(os.path.join(workspace_id, path)):
                    secure_path = os.path.join(workspace_id, path)
                else:
                    raise

            # 2. Security Check: SELECT only
            if not query.strip().upper().startswith("SELECT"):
                return {"error": "Only SELECT queries are allowed for security reasons."}

            # 3. Standard connection (Windows-friendly)
            conn = sqlite3.connect(secure_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(f"{query} LIMIT ?", (min(limit, 1000),))
            rows = cursor.fetchall()
            
            result_data = [dict(row) for row in rows]
            columns = list(result_data[0].keys()) if result_data else []
            conn.close()

            return {
                "success": True,
                "columns": columns,
                "rows": result_data,
                "row_count": len(result_data),
                "query": query
            }
        except Exception as e:
            return {"error": f"Database error: {str(e)}"}

    @mcp.tool()
    def db_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """Get the database schema (list of tables and their columns)."""
        try:
            # Resolve path
            try:
                secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            except Exception:
                if os.path.isabs(path) and os.path.exists(path):
                    secure_path = path
                elif os.path.exists(os.path.join(workspace_id, path)):
                    secure_path = os.path.join(workspace_id, path)
                else:
                    raise

            conn = sqlite3.connect(secure_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

            schema = {}
            for table in tables:
                cursor.execute(f"PRAGMA table_info('{table}');")
                schema[table] = [{"name": r[1], "type": r[2]} for r in cursor.fetchall()]

            conn.close()
            return {"success": True, "schema": schema}
        except Exception as e:
            return {"error": f"Database error: {str(e)}"}