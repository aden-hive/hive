"""Account info tool — lets the LLM query connected accounts at runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register account info tools with the MCP server."""

    @mcp.tool()
    def get_account_info(provider: str = "") -> dict:
        """List connected accounts and their identities.

        Call with no arguments to see all connected accounts.
        Call with provider="google" to filter by provider type.

        Returns account IDs, provider types, and identity labels
        (email, username, workspace) for each connected account.
        """
        if credentials is None:
            return {"accounts": [], "message": "No credential store configured"}
        if provider:
            accounts = credentials.list_accounts(provider)
        else:
            accounts = credentials.get_all_account_info()
        return {"accounts": accounts, "count": len(accounts)}
