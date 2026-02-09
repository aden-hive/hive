"""Tests for Airtable tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.airtable_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def airtable_list_bases_fn(mcp: FastMCP):
    """Register and return the airtable_list_bases tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["airtable_list_bases"].fn


@pytest.fixture
def airtable_list_records_fn(mcp: FastMCP):
    """Register and return the airtable_list_records tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["airtable_list_records"].fn


@pytest.fixture
def airtable_create_record_fn(mcp: FastMCP):
    """Register and return the airtable_create_record tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["airtable_create_record"].fn


@pytest.fixture
def airtable_update_record_fn(mcp: FastMCP):
    """Register and return the airtable_update_record tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["airtable_update_record"].fn


class TestAirtableCredentials:
    """Tests for Airtable credential handling."""

    def test_no_credentials_returns_error(self, airtable_list_bases_fn, monkeypatch):
        """List bases without credentials returns helpful error."""
        monkeypatch.delenv("AIRTABLE_API_TOKEN", raising=False)
        monkeypatch.delenv("AIRTABLE_ACCESS_TOKEN", raising=False)

        result = airtable_list_bases_fn()

        assert "error" in result
        assert "Airtable credentials not configured" in result["error"]
        assert "help" in result


class TestAirtableListBases:
    """Tests for airtable_list_bases tool."""

    def test_list_bases_success(self, airtable_list_bases_fn, monkeypatch):
        """List bases returns base list."""
        monkeypatch.setenv("AIRTABLE_API_TOKEN", "pat_test-token")

        with (
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "bases": [
                    {"id": "app123", "name": "Leads", "permissionLevel": "edit"},
                ]
            }
            mock_request.return_value = mock_resp

            result = airtable_list_bases_fn()

        assert result["success"] is True
        assert result["count"] == 1
        assert result["bases"][0]["id"] == "app123"
        assert result["bases"][0]["name"] == "Leads"

    def test_list_bases_api_error(self, airtable_list_bases_fn, monkeypatch):
        """API error returns appropriate message."""
        monkeypatch.setenv("AIRTABLE_API_TOKEN", "pat_test-token")

        with (
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_request.return_value = mock_resp

            result = airtable_list_bases_fn()

        assert "error" in result
        assert "Invalid or expired" in result["error"]


class TestAirtableListRecords:
    """Tests for airtable_list_records tool."""

    def test_list_records_success(self, airtable_list_records_fn, monkeypatch):
        """List records returns record list."""
        monkeypatch.setenv("AIRTABLE_API_TOKEN", "pat_test-token")

        with (
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "records": [
                    {
                        "id": "rec123",
                        "createdTime": "2026-01-01T00:00:00.000Z",
                        "fields": {"Name": "Lead 1", "Status": "Contacted"},
                    }
                ],
            }
            mock_request.return_value = mock_resp

            result = airtable_list_records_fn(
                base_id="app123",
                table_id_or_name="Leads",
            )

        assert result["success"] is True
        assert result["count"] == 1
        assert result["records"][0]["id"] == "rec123"
        assert result["records"][0]["fields"]["Name"] == "Lead 1"


class TestAirtableCreateRecord:
    """Tests for airtable_create_record tool."""

    def test_create_record_success(self, airtable_create_record_fn, monkeypatch):
        """Create record returns created record."""
        monkeypatch.setenv("AIRTABLE_API_TOKEN", "pat_test-token")

        with (
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "recNEW",
                "createdTime": "2026-01-01T00:00:00.000Z",
                "fields": {"Name": "Acme", "Status": "Contacted"},
            }
            mock_request.return_value = mock_resp

            result = airtable_create_record_fn(
                base_id="app123",
                table_id_or_name="Leads",
                fields={"Name": "Acme", "Status": "Contacted"},
            )

        assert result["success"] is True
        assert result["id"] == "recNEW"
        assert result["fields"]["Status"] == "Contacted"


class TestAirtableUpdateRecord:
    """Tests for airtable_update_record tool."""

    def test_update_record_success(self, airtable_update_record_fn, monkeypatch):
        """Update record returns updated record."""
        monkeypatch.setenv("AIRTABLE_API_TOKEN", "pat_test-token")

        with (
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "rec123",
                "createdTime": "2026-01-01T00:00:00.000Z",
                "fields": {"Name": "Acme", "Status": "Contacted"},
            }
            mock_request.return_value = mock_resp

            result = airtable_update_record_fn(
                base_id="app123",
                table_id_or_name="Leads",
                record_id="rec123",
                fields={"Status": "Contacted"},
            )

        assert result["success"] is True
        assert result["id"] == "rec123"
        assert result["fields"]["Status"] == "Contacted"
