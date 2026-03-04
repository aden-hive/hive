"""Tests for airtable_tool - Record CRUD and base metadata."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.airtable_tool.airtable_tool import register_tools

ENV = {"AIRTABLE_PAT": "pat-test-token"}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


RECORD_DATA = {
    "id": "recABC123",
    "createdTime": "2024-01-15T10:30:00.000Z",
    "fields": {"Name": "Project Alpha", "Status": "Active"},
}


class TestAirtableListRecords:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["airtable_list_records"](base_id="appXXX", table_name="Tasks")
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_list_records"](base_id="", table_name="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {"records": [RECORD_DATA]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_list_records"](base_id="appXXX", table_name="Tasks")

        assert result["count"] == 1
        assert result["records"][0]["fields"]["Name"] == "Project Alpha"

    def test_pagination(self, tool_fns):
        data = {"records": [RECORD_DATA], "offset": "itrXXX/recXXX"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_list_records"](base_id="appXXX", table_name="Tasks")

        assert result["has_more"] is True
        assert result["offset"] == "itrXXX/recXXX"


class TestAirtableGetRecord:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_get_record"](base_id="", table_name="", record_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.get",
                return_value=_mock_resp(RECORD_DATA),
            ),
        ):
            result = tool_fns["airtable_get_record"](
                base_id="appXXX", table_name="Tasks", record_id="recABC123"
            )

        assert result["id"] == "recABC123"
        assert result["fields"]["Status"] == "Active"


class TestAirtableCreateRecords:
    def test_missing_records(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_create_records"](
                base_id="appXXX", table_name="Tasks", records=""
            )
        assert "error" in result

    def test_invalid_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_create_records"](
                base_id="appXXX", table_name="Tasks", records="not json"
            )
        assert "error" in result

    def test_too_many_records(self, tool_fns):
        import json

        records = json.dumps([{"fields": {"Name": f"Item {i}"}} for i in range(11)])
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_create_records"](
                base_id="appXXX", table_name="Tasks", records=records
            )
        assert "error" in result
        assert "10" in result["error"]

    def test_successful_create(self, tool_fns):
        data = {"records": [RECORD_DATA]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_create_records"](
                base_id="appXXX",
                table_name="Tasks",
                records='[{"fields": {"Name": "Project Alpha", "Status": "Active"}}]',
            )

        assert result["result"] == "created"
        assert result["count"] == 1


class TestAirtableUpdateRecords:
    def test_successful_update(self, tool_fns):
        updated = dict(RECORD_DATA)
        updated["fields"] = {"Name": "Project Alpha", "Status": "Done"}
        data = {"records": [updated]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.patch",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_update_records"](
                base_id="appXXX",
                table_name="Tasks",
                records='[{"id": "recABC123", "fields": {"Status": "Done"}}]',
            )

        assert result["result"] == "updated"
        assert result["count"] == 1


class TestAirtableListBases:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["airtable_list_bases"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "bases": [
                {"id": "appXXX", "name": "My Base", "permissionLevel": "create"},
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_list_bases"]()

        assert result["count"] == 1
        assert result["bases"][0]["name"] == "My Base"


class TestAirtableGetBaseSchema:
    def test_missing_base_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["airtable_get_base_schema"](base_id="")
        assert "error" in result

    def test_successful_schema(self, tool_fns):
        data = {
            "tables": [
                {
                    "id": "tblXXX",
                    "name": "Tasks",
                    "fields": [
                        {"id": "fldAAA", "name": "Name", "type": "singleLineText"},
                        {"id": "fldBBB", "name": "Status", "type": "singleSelect"},
                    ],
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.airtable_tool.airtable_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["airtable_get_base_schema"](base_id="appXXX")

        assert result["count"] == 1
        assert result["tables"][0]["name"] == "Tasks"
        assert len(result["tables"][0]["fields"]) == 2
