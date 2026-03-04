"""
Google Sheets Tool - Read and manage spreadsheet data via Sheets API v4.

Supports:
- Google Sheets API v4 with API key (read-only for public sheets)
- Get spreadsheet metadata, read cell ranges, list sheets

API Reference: https://developers.google.com/sheets/api/reference/rest
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def _get_credentials(credentials: CredentialStoreAdapter | None) -> str | None:
    """Return the Google Sheets API key."""
    if credentials is not None:
        return credentials.get("google_sheets_key")
    return os.getenv("GOOGLE_SHEETS_API_KEY")


def _get(path: str, api_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a GET to the Google Sheets API."""
    all_params = dict(params or {})
    all_params["key"] = api_key
    try:
        resp = httpx.get(
            f"{API_BASE}{path}",
            params=all_params,
            timeout=30.0,
        )
        if resp.status_code == 400:
            return {"error": f"Bad request: {resp.text[:500]}"}
        if resp.status_code == 403:
            return {
                "error": "Forbidden. The spreadsheet may not be public or the API key is invalid."
            }
        if resp.status_code == 404:
            return {"error": "Spreadsheet not found."}
        if resp.status_code != 200:
            return {"error": f"Google Sheets API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Google Sheets timed out"}
    except Exception as e:
        return {"error": f"Google Sheets request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "GOOGLE_SHEETS_API_KEY not set",
        "help": "Create an API key at https://console.cloud.google.com/apis/credentials",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Sheets tools with the MCP server."""

    @mcp.tool()
    def sheets_get_spreadsheet(
        spreadsheet_id: str,
    ) -> dict[str, Any]:
        """
        Get metadata for a Google Sheets spreadsheet including all sheet names.

        Args:
            spreadsheet_id: The spreadsheet ID from the URL (required)

        Returns:
            Dict with spreadsheet title and list of sheets (name, index, row/column counts)
        """
        api_key = _get_credentials(credentials)
        if not api_key:
            return _auth_error()
        if not spreadsheet_id:
            return {"error": "spreadsheet_id is required"}

        data = _get(
            f"/{spreadsheet_id}",
            api_key,
            {"fields": "spreadsheetId,properties.title,sheets.properties"},
        )
        if "error" in data:
            return data

        props = data.get("properties", {})
        sheets = []
        for s in data.get("sheets", []):
            sp = s.get("properties", {})
            grid = sp.get("gridProperties", {})
            sheets.append(
                {
                    "title": sp.get("title", ""),
                    "sheet_id": sp.get("sheetId"),
                    "index": sp.get("index", 0),
                    "row_count": grid.get("rowCount", 0),
                    "column_count": grid.get("columnCount", 0),
                }
            )

        return {
            "spreadsheet_id": data.get("spreadsheetId", ""),
            "title": props.get("title", ""),
            "sheets": sheets,
            "sheet_count": len(sheets),
        }

    @mcp.tool()
    def sheets_read_range(
        spreadsheet_id: str,
        range: str,
        value_render: str = "FORMATTED_VALUE",
    ) -> dict[str, Any]:
        """
        Read a range of cells from a Google Sheets spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID from the URL (required)
            range: A1 notation range e.g. "Sheet1!A1:D10" or "Sheet1" (required)
            value_render: How values are rendered: FORMATTED_VALUE,
                UNFORMATTED_VALUE, or FORMULA (default FORMATTED_VALUE)

        Returns:
            Dict with cell values as 2D array, range info, and row/column counts
        """
        api_key = _get_credentials(credentials)
        if not api_key:
            return _auth_error()
        if not spreadsheet_id or not range:
            return {"error": "spreadsheet_id and range are required"}

        data = _get(
            f"/{spreadsheet_id}/values/{range}",
            api_key,
            {"valueRenderOption": value_render},
        )
        if "error" in data:
            return data

        values = data.get("values", [])
        return {
            "range": data.get("range", ""),
            "values": values,
            "row_count": len(values),
            "column_count": max((len(row) for row in values), default=0),
        }

    @mcp.tool()
    def sheets_batch_read(
        spreadsheet_id: str,
        ranges: str,
        value_render: str = "FORMATTED_VALUE",
    ) -> dict[str, Any]:
        """
        Read multiple ranges from a Google Sheets spreadsheet in one request.

        Args:
            spreadsheet_id: The spreadsheet ID from the URL (required)
            ranges: Comma-separated A1 notation ranges e.g. "Sheet1!A1:B5,Sheet2!A1:C3" (required)
            value_render: How values are rendered: FORMATTED_VALUE, UNFORMATTED_VALUE, FORMULA

        Returns:
            Dict with value ranges for each requested range
        """
        api_key = _get_credentials(credentials)
        if not api_key:
            return _auth_error()
        if not spreadsheet_id or not ranges:
            return {"error": "spreadsheet_id and ranges are required"}

        range_list = [r.strip() for r in ranges.split(",") if r.strip()]
        params: dict[str, Any] = {"valueRenderOption": value_render}
        for r in range_list:
            params.setdefault("ranges", [])
            if isinstance(params["ranges"], list):
                params["ranges"].append(r)

        data = _get(f"/{spreadsheet_id}/values:batchGet", api_key, params)
        if "error" in data:
            return data

        results = []
        for vr in data.get("valueRanges", []):
            values = vr.get("values", [])
            results.append(
                {
                    "range": vr.get("range", ""),
                    "values": values,
                    "row_count": len(values),
                }
            )
        return {"ranges": results, "count": len(results)}
