"""Register Discord tools with FastMCP."""

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: "CredentialStoreAdapter | None" = None,
) -> None:
    """Register Discord tools with FastMCP server."""
    from .discord_tool import register_tools as _register
    _register(mcp, credentials)
