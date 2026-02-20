from __future__ import annotations

from typing import Callable
from fastmcp import FastMCP


def get_tool_fn(mcp: FastMCP, name: str) -> Callable:
    """
    Centralized helper for tests/examples.
    If FastMCP exposes a public getter later, update only here.
    """
    return mcp._tool_manager._tools[name].fn
