"""
MongoDB Tool - Perform database operations (CRUD) via MongoDB Atlas.

Supports MongoDB Connection String URIs for authentication.
"""

from .mongodb_tool import register_tools

__all__ = ["register_tools"]
