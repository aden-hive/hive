"""Supabase tool registration."""

from typing import Any, TYPE_CHECKING
from fastmcp import FastMCP

from .supabase_tool import SupabaseClient

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager


def register_tools(mcp: FastMCP, credentials: "CredentialManager | None" = None) -> None:
    """Register Supabase tools with the MCP server."""

    def _get_client() -> SupabaseClient:
        # Load credentials
        url = None
        key = None
        if credentials:
            url = credentials.get("supabase_url")
            key = (
                credentials.get("supabase_service_role_key")
                or credentials.get("supabase_anon_key")
            )

        return SupabaseClient(url=url, key=key)

    @mcp.tool()
    def supabase_select(
        table: str,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        limit: int = 100,
        order: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Query a Supabase table using PostgREST syntax.

        Args:
            table: Table name
            columns: Comma-separated columns to select (default: "*")
            filters: Dictionary of filters (e.g., {"id": "eq.5"}).
                     See PostgREST docs for operators.
            limit: Max rows to return
            order: Order by string (e.g., "created_at.desc")
        """
        client = _get_client()
        return client.select(table, columns, filters, limit, order)

    @mcp.tool()
    def supabase_insert(
        table: str,
        data: list[dict[str, Any]] | dict[str, Any],
        upsert: bool = False,
    ) -> Any:
        """
        Insert rows into a Supabase table.

        Args:
            table: Table name
            data: Single record (dict) or list of records
            upsert: If True, merges duplicates based on primary key
        """
        client = _get_client()
        return client.insert(table, data, upsert)

    @mcp.tool()
    def supabase_update(
        table: str,
        data: dict[str, Any],
        filters: dict[str, str],
    ) -> Any:
        """
        Update rows in a Supabase table.

        Args:
            table: Table name
            data: Fields to update
            filters: Conditions to match rows (REQUIRED)
        """
        client = _get_client()
        return client.update(table, data, filters)

    @mcp.tool()
    def supabase_delete(
        table: str,
        filters: dict[str, str],
    ) -> Any:
        """
        Delete rows from a Supabase table.

        Args:
            table: Table name
            filters: Conditions to match rows (REQUIRED)
        """
        client = _get_client()
        return client.delete(table, filters)

    @mcp.tool()
    def supabase_upload_file(
        bucket: str,
        path: str,
        local_file_path: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a file to Supabase Storage.

        Args:
            bucket: Storage bucket name
            path: Destination path in bucket (e.g., "folder/image.png")
            local_file_path: Absolute path to local file
            content_type: MIME type (optional, auto-guessed if missing)
        """
        client = _get_client()
        return client.upload_file(bucket, path, local_file_path, content_type)

    @mcp.tool()
    def supabase_download_file(
        bucket: str,
        path: str,
        local_destination: str,
    ) -> dict[str, str]:
        """
        Download a file from Supabase Storage.

        Args:
            bucket: Storage bucket name
            path: Path in bucket
            local_destination: Local path to save file
        """
        client = _get_client()
        return client.download_file(bucket, path, local_destination)
