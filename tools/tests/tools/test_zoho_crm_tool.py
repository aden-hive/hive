"""Tests for zoho_crm_tool - Zoho CRM lead, contact, and deal management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.zoho_crm_tool.zoho_crm_tool import register_tools

ENV = {"ZOHO_CRM_ACCESS_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestZohoCrmListRecords:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["zoho_crm_list_records"](module="Leads")
        assert "error" in result

    def test_missing_module(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoho_crm_list_records"](module="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {"id": "123", "Last_Name": "Smith", "Company": "Acme"},
            ],
            "info": {"count": 1, "more_records": False, "page": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_list_records"](module="Leads")

        assert result["module"] == "Leads"
        assert len(result["records"]) == 1


class TestZohoCrmGetRecord:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoho_crm_get_record"](module="", record_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "data": [{"id": "123", "Last_Name": "Smith", "Email": "smith@test.com"}],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_get_record"](module="Contacts", record_id="123")

        assert result["record"]["Last_Name"] == "Smith"


class TestZohoCrmCreateRecord:
    def test_missing_data(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoho_crm_create_record"](module="Leads")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "status": "success",
                    "message": "record added",
                    "details": {"id": "456"},
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_create_record"](
                module="Leads", record_data={"Last_Name": "Doe", "Company": "Test"}
            )

        assert result["status"] == "success"
        assert result["id"] == "456"


class TestZohoCrmSearchRecords:
    def test_no_search_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoho_crm_search_records"](module="Leads")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "data": [{"id": "123", "Last_Name": "Smith"}],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_search_records"](module="Leads", word="Smith")

        assert len(result["results"]) == 1


class TestZohoCrmListModules:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "modules": [
                {
                    "api_name": "Leads",
                    "module_name": "Leads",
                    "plural_label": "Leads",
                    "editable": True,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_list_modules"]()

        assert len(result["modules"]) == 1
        assert result["modules"][0]["api_name"] == "Leads"


class TestZohoCrmAddNote:
    def test_missing_content(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoho_crm_add_note"](
                module="Leads", record_id="123", title="Note", content=""
            )
        assert "error" in result

    def test_successful_add(self, tool_fns):
        mock_resp = {"data": [{"status": "success", "details": {"id": "note-1"}}]}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["zoho_crm_add_note"](
                module="Leads", record_id="123", title="Note", content="Follow up"
            )

        assert result["status"] == "success"
