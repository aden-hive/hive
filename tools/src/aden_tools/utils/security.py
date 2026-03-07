"""
Security utilities for Aden Tools.
"""

from __future__ import annotations

GRAPH_BASE = "https://graph.microsoft.com/v1.0/me"


def sanitize_path_param(param: str, param_name: str = "parameter") -> str:
    """Sanitize URL path parameters to prevent path traversal."""
    if "/" in param or ".." in param:
        raise ValueError(f"Invalid {param_name}: cannot contain '/' or '..'")
    return param
