"""
Integration tests for Google Sheets tool against the real Google Sheets API.

These tests create a real spreadsheet, perform CRUD operations, and clean up.
They require a valid Google OAuth2 token with Sheets + Drive scopes.

Run with:
    PYTHONPATH=core:tools/src python -m pytest \
        tools/src/aden_tools/tools/google_sheets_tool/tests/test_google_sheets_integration.py -v

Skipped automatically if no Google credential is available.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from aden_tools.tools.google_sheets_tool.google_sheets_tool import (
    _GoogleSheetsClient,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _get_google_token() -> str | None:
    """Try to get a Google OAuth token from the credential store.

    Uses CredentialStoreAdapter.default() which wires up AdenCachedStorage
    with the provider index, so ``get("google")`` resolves to the Aden-managed
    OAuth token (compound ID) rather than requiring a plain ``google.enc`` file.
    """
    try:
        from aden_tools.credentials import CredentialStoreAdapter

        adapter = CredentialStoreAdapter.default()
        return adapter.get("google")
    except Exception:
        return None


_TOKEN = _get_google_token()

pytestmark = pytest.mark.skipif(
    _TOKEN is None,
    reason="No Google credential available (need credential store with 'google' token)",
)


def _delete_spreadsheet(token: str, spreadsheet_id: str) -> None:
    """Delete a spreadsheet via Google Drive API (cleanup helper)."""
    httpx.delete(
        f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )


@pytest.fixture()
def client() -> _GoogleSheetsClient:
    """Create a real client with the stored Google token."""
    assert _TOKEN is not None
    return _GoogleSheetsClient(_TOKEN)


@pytest.fixture()
def spreadsheet(client: _GoogleSheetsClient):
    """Create a temporary spreadsheet and delete it after the test."""
    unique = uuid.uuid4().hex[:8]
    title = f"hive-integration-test-{unique}"
    result = client.create_spreadsheet(title, sheet_titles=["Data", "Extra"])
    assert "error" not in result, f"Failed to create spreadsheet: {result}"
    spreadsheet_id = result["spreadsheetId"]
    yield spreadsheet_id, result
    # Cleanup: delete via Drive API
    assert _TOKEN is not None
    _delete_spreadsheet(_TOKEN, spreadsheet_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateAndGetSpreadsheet:
    def test_create_spreadsheet(self, spreadsheet):
        """Creating a spreadsheet returns a valid ID and the requested sheets."""
        spreadsheet_id, result = spreadsheet
        assert spreadsheet_id
        sheets = result.get("sheets", [])
        titles = [s["properties"]["title"] for s in sheets]
        assert "Data" in titles
        assert "Extra" in titles

    def test_get_spreadsheet_metadata(self, client, spreadsheet):
        """Getting a spreadsheet returns its metadata."""
        spreadsheet_id, _ = spreadsheet
        result = client.get_spreadsheet(spreadsheet_id)
        assert "error" not in result, f"Failed to get spreadsheet: {result}"
        assert result["spreadsheetId"] == spreadsheet_id
        assert "properties" in result


class TestReadWriteValues:
    def test_write_and_read_values(self, client, spreadsheet):
        """Write values to a range and read them back."""
        spreadsheet_id, _ = spreadsheet
        values = [["Name", "Score"], ["Alice", "95"], ["Bob", "87"]]

        # Write
        update_result = client.update_values(spreadsheet_id, "Data!A1:B3", values)
        assert "error" not in update_result, f"Failed to update: {update_result}"

        # Read back
        get_result = client.get_values(spreadsheet_id, "Data!A1:B3")
        assert "error" not in get_result, f"Failed to get values: {get_result}"
        assert get_result["values"] == values

    def test_append_values(self, client, spreadsheet):
        """Append rows to an existing range."""
        spreadsheet_id, _ = spreadsheet

        # Seed initial data
        client.update_values(spreadsheet_id, "Data!A1:B1", [["Name", "Score"]])

        # Append
        append_result = client.append_values(spreadsheet_id, "Data!A1", [["Charlie", "72"]])
        assert "error" not in append_result, f"Failed to append: {append_result}"

        # Verify row 2 has the appended data
        get_result = client.get_values(spreadsheet_id, "Data!A2:B2")
        assert "error" not in get_result, f"Failed to read: {get_result}"
        assert get_result["values"] == [["Charlie", "72"]]

    def test_clear_values(self, client, spreadsheet):
        """Clear a range and verify it's empty."""
        spreadsheet_id, _ = spreadsheet

        # Write data
        client.update_values(spreadsheet_id, "Data!A1:B1", [["hello", "world"]])

        # Clear
        clear_result = client.clear_values(spreadsheet_id, "Data!A1:B1")
        assert "error" not in clear_result, f"Failed to clear: {clear_result}"

        # Verify empty
        get_result = client.get_values(spreadsheet_id, "Data!A1:B1")
        assert "error" not in get_result
        # Google returns no "values" key for empty ranges
        assert "values" not in get_result


class TestBatchOperations:
    def test_batch_update_values(self, client, spreadsheet):
        """Batch update multiple ranges at once."""
        spreadsheet_id, _ = spreadsheet
        data = [
            {"range": "Data!A1:A2", "values": [["X"], ["Y"]]},
            {"range": "Data!C1:C2", "values": [["P"], ["Q"]]},
        ]

        result = client.batch_update_values(spreadsheet_id, data)
        assert "error" not in result, f"Batch update failed: {result}"

        # Verify both ranges
        a_vals = client.get_values(spreadsheet_id, "Data!A1:A2")
        c_vals = client.get_values(spreadsheet_id, "Data!C1:C2")
        assert a_vals["values"] == [["X"], ["Y"]]
        assert c_vals["values"] == [["P"], ["Q"]]

    def test_batch_clear_values(self, client, spreadsheet):
        """Batch clear multiple ranges."""
        spreadsheet_id, _ = spreadsheet

        # Write to two ranges
        client.batch_update_values(
            spreadsheet_id,
            [
                {"range": "Data!A1", "values": [["keep"]]},
                {"range": "Data!B1", "values": [["remove"]]},
                {"range": "Data!C1", "values": [["remove"]]},
            ],
        )

        # Batch clear B1 and C1
        result = client.batch_clear_values(spreadsheet_id, ["Data!B1", "Data!C1"])
        assert "error" not in result, f"Batch clear failed: {result}"

        # A1 should still have data
        a_vals = client.get_values(spreadsheet_id, "Data!A1")
        assert a_vals["values"] == [["keep"]]


class TestSheetManagement:
    def test_add_and_delete_sheet(self, client, spreadsheet):
        """Add a new sheet tab and then delete it."""
        spreadsheet_id, _ = spreadsheet

        # Add sheet
        add_result = client.add_sheet(spreadsheet_id, "Temp Sheet")
        assert "error" not in add_result, f"Add sheet failed: {add_result}"

        # Extract the new sheet ID
        new_sheet_id = add_result["replies"][0]["addSheet"]["properties"]["sheetId"]
        assert isinstance(new_sheet_id, int)

        # Delete it
        del_result = client.delete_sheet(spreadsheet_id, new_sheet_id)
        assert "error" not in del_result, f"Delete sheet failed: {del_result}"

        # Verify the sheet is gone
        meta = client.get_spreadsheet(spreadsheet_id)
        sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
        assert "Temp Sheet" not in sheet_titles


class TestMCPToolRegistration:
    """Test that the MCP tools work end-to-end with real credentials."""

    def test_tools_via_register(self):
        """Register tools via the public API and call one."""
        from unittest.mock import MagicMock

        from aden_tools.credentials import CredentialStoreAdapter
        from aden_tools.tools.google_sheets_tool.google_sheets_tool import (
            register_tools,
        )

        creds = CredentialStoreAdapter.default()

        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=creds)

        # Find the create tool
        create_fn = next(
            f for f in registered_fns if f.__name__ == "google_sheets_create_spreadsheet"
        )

        unique = uuid.uuid4().hex[:8]
        result = create_fn(title=f"hive-mcp-test-{unique}")
        assert "error" not in result, f"MCP create failed: {result}"

        spreadsheet_id = result["spreadsheetId"]
        assert spreadsheet_id

        # Cleanup
        assert _TOKEN is not None
        _delete_spreadsheet(_TOKEN, spreadsheet_id)
