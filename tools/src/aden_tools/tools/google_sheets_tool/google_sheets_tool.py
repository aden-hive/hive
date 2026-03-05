"""
Google Sheets Tool - Read, write, and manage Google Sheets via Google Sheets API v4.

Supports:
- OAuth2 access tokens via the credential store (key: "google")
- Environment variable: GOOGLE_ACCESS_TOKEN

API Reference: https://developers.google.com/sheets/api/reference/rest
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class _GoogleSheetsClient:
    """Internal client wrapping Google Sheets API v4 calls."""

    def __init__(self, access_token: str):
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Google Sheets access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Google API scopes."}
        if response.status_code == 404:
            return {"error": "Spreadsheet or range not found"}
        if response.status_code == 429:
            return {"error": "Google API rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Google Sheets API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def get_spreadsheet(
        self,
        spreadsheet_id: str,
        include_grid_data: bool = False,
    ) -> dict[str, Any]:
        """Get spreadsheet metadata."""
        params = {}
        if include_grid_data:
            params["includeGridData"] = "true"

        response = httpx.get(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_spreadsheet(
        self,
        title: str,
        sheet_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new spreadsheet."""
        body: dict[str, Any] = {"properties": {"title": title}}

        if sheet_titles:
            body["sheets"] = [
                {"properties": {"title": sheet_title}} for sheet_title in sheet_titles
            ]

        response = httpx.post(
            GOOGLE_SHEETS_API_BASE,
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> dict[str, Any]:
        """Get values from a range."""
        params = {"valueRenderOption": value_render_option}

        response = httpx.get(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Update values in a range."""
        params = {"valueInputOption": value_input_option}
        body = {"values": values}

        response = httpx.put(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}",
            headers=self._headers,
            params=params,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Append values to a sheet."""
        params = {"valueInputOption": value_input_option}
        body = {"values": values}

        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}:append",
            headers=self._headers,
            params=params,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def clear_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> dict[str, Any]:
        """Clear values in a range."""
        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}:clear",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def batch_update_values(
        self,
        spreadsheet_id: str,
        data: list[dict[str, Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Batch update multiple ranges."""
        body = {
            "valueInputOption": value_input_option,
            "data": data,
        }

        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values:batchUpdate",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def batch_clear_values(
        self,
        spreadsheet_id: str,
        ranges: list[str],
    ) -> dict[str, Any]:
        """Batch clear multiple ranges."""
        body = {"ranges": ranges}

        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values:batchClear",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_sheet(
        self,
        spreadsheet_id: str,
        title: str,
        row_count: int = 1000,
        column_count: int = 26,
    ) -> dict[str, Any]:
        """Add a new sheet to a spreadsheet."""
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": title,
                            "gridProperties": {
                                "rowCount": row_count,
                                "columnCount": column_count,
                            },
                        }
                    }
                }
            ]
        }

        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}:batchUpdate",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
    ) -> dict[str, Any]:
        """Delete a sheet from a spreadsheet."""
        body = {"requests": [{"deleteSheet": {"sheetId": sheet_id}}]}

        response = httpx.post(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}:batchUpdate",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Sheets tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Google access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("google")
            # Defensive check: ensure we get a string, not a complex object
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('google'), got {type(token).__name__}"
                )
            return token
        return os.getenv("GOOGLE_ACCESS_TOKEN")

    def _get_client() -> _GoogleSheetsClient | dict[str, str]:
        """Get a Google Sheets client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Google Sheets credentials not configured",
                "help": (
                    "Set GOOGLE_ACCESS_TOKEN environment variable "
                    "or configure 'google' via credential store"
                ),
            }
        return _GoogleSheetsClient(token)

    def _sanitize_error(e: Exception) -> str:
        """Sanitize exception message to avoid leaking sensitive data like tokens."""
        msg = str(e)
        if "Bearer" in msg or "Authorization" in msg:
            return f"{type(e).__name__}: Request failed (details redacted for security)"
        if len(msg) > 200:
            return f"{type(e).__name__}: {msg[:200]}..."
        return msg

    # --- Spreadsheet Management ---

    @mcp.tool()
    def google_sheets_get_spreadsheet(
        spreadsheet_id: str,
        include_grid_data: bool = False,
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Get Google Sheets spreadsheet metadata.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            include_grid_data: Whether to include cell data (default False)

        Returns:
            Dict with spreadsheet metadata or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_spreadsheet(spreadsheet_id, include_grid_data)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def google_sheets_create_spreadsheet(
        title: str,
        sheet_titles: list[str] | None = None,
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Create a new Google Sheets spreadsheet.

        Args:
            title: The spreadsheet title
            sheet_titles: Optional list of sheet/tab names to create

        Returns:
            Dict with created spreadsheet data or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_spreadsheet(title, sheet_titles)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    # --- Reading Data ---

    @mcp.tool()
    def google_sheets_get_values(
        spreadsheet_id: str,
        range_name: str,
        value_render_option: str = "FORMATTED_VALUE",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Get values from a Google Sheets range.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            range_name: The A1 notation range (e.g., "Sheet1!A1:B10")
            value_render_option: How to render values
                (FORMATTED_VALUE, UNFORMATTED_VALUE, FORMULA)

        Returns:
            Dict with values or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_values(spreadsheet_id, range_name, value_render_option)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    # --- Writing Data ---

    @mcp.tool()
    def google_sheets_update_values(
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Update values in a Google Sheets range.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            range_name: The A1 notation range (e.g., "Sheet1!A1:B10")
            values: 2D array of values to write
            value_input_option: How to interpret input
                (USER_ENTERED parses, RAW stores as-is)

        Returns:
            Dict with update result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_values(spreadsheet_id, range_name, values, value_input_option)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def google_sheets_append_values(
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Append values to a Google Sheets range.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            range_name: The A1 notation range (e.g., "Sheet1!A1")
            values: 2D array of values to append
            value_input_option: How to interpret input
                (USER_ENTERED parses, RAW stores as-is)

        Returns:
            Dict with append result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.append_values(spreadsheet_id, range_name, values, value_input_option)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def google_sheets_clear_values(
        spreadsheet_id: str,
        range_name: str,
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Clear values in a Google Sheets range.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            range_name: The A1 notation range (e.g., "Sheet1!A1:B10")

        Returns:
            Dict with clear result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.clear_values(spreadsheet_id, range_name)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    # --- Batch Operations ---

    @mcp.tool()
    def google_sheets_batch_update_values(
        spreadsheet_id: str,
        data: list[dict[str, Any]],
        value_input_option: str = "USER_ENTERED",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Batch update multiple ranges in a Google Sheets spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            data: List of update objects with "range" and "values" keys
            value_input_option: How to interpret input
                (USER_ENTERED parses, RAW stores as-is)

        Returns:
            Dict with batch update result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.batch_update_values(spreadsheet_id, data, value_input_option)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def google_sheets_batch_clear_values(
        spreadsheet_id: str,
        ranges: list[str],
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Batch clear multiple ranges in a Google Sheets spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            ranges: List of A1 notation ranges to clear

        Returns:
            Dict with batch clear result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.batch_clear_values(spreadsheet_id, ranges)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    # --- Sheet Management ---

    @mcp.tool()
    def google_sheets_add_sheet(
        spreadsheet_id: str,
        title: str,
        row_count: int = 1000,
        column_count: int = 26,
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Add a new sheet/tab to a Google Sheets spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            title: The sheet title
            row_count: Number of rows (default 1000)
            column_count: Number of columns (default 26)

        Returns:
            Dict with add sheet result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.add_sheet(spreadsheet_id, title, row_count, column_count)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def google_sheets_delete_sheet(
        spreadsheet_id: str,
        sheet_id: int,
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Delete a sheet/tab from a Google Sheets spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID (from the URL)
            sheet_id: The numeric sheet ID (not the title)

        Returns:
            Dict with delete result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_sheet(spreadsheet_id, sheet_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}
