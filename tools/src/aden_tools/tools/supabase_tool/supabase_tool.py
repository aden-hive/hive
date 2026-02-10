"""
Supabase Tool - Mock Implementation for Demo.
"""
from __future__ import annotations
from typing import Any, Dict
from fastmcp import FastMCP

def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    @mcp.tool()
    def supabase_fetch(table: str, columns: str = "*", limit: int = 10) -> Dict:
        """Fetch rows from a Supabase table (MOCK)."""
        # Simulated data so you can show Vincent it works!
        mock_data = [
            {"id": 1, "name": "Vincent", "role": "CEO"},
            {"id": 2, "name": "User", "role": "Founding Engineer Candidate"}
        ]
        return {
            "success": True, 
            "message": f"MOCK DATA: Successfully fetched from {table}",
            "data": mock_data[:limit]
        }

    @mcp.tool()
    def supabase_store(table: str, record: Dict[str, Any]) -> Dict:
        """Upsert a record into a table (MOCK)."""
        return {
            "success": True,
            "message": f"MOCK SUCCESS: Record stored in {table}",
            "record_received": record
        }