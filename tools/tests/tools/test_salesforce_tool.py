"""Tests for salesforce_tool - Salesforce CRM REST API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.salesforce_tool.salesforce_tool import register_tools

ENV = {
    "SALESFORCE_ACCESS_TOKEN": "00Dxx0000000000!test_token",
    "SALESFORCE_INSTANCE_URL": "https://acme.my.salesforce.com",
}


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


class TestSalesforceSOQLQuery:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["salesforce_soql_query"](query="SELECT Id FROM Lead")
        assert "error" in result

    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["salesforce_soql_query"](query="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        data = {
            "totalSize": 2,
            "done": True,
            "records": [
                {"Id": "00Q1", "Name": "Jane Smith", "attributes": {"type": "Lead"}},
                {"Id": "00Q2", "Name": "John Doe", "attributes": {"type": "Lead"}},
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["salesforce_soql_query"](query="SELECT Id, Name FROM Lead")

        assert result["total_size"] == 2
        assert result["done"] is True
        assert len(result["records"]) == 2

    def test_pagination(self, tool_fns):
        data = {
            "totalSize": 5000,
            "done": False,
            "nextRecordsUrl": "/services/data/v62.0/query/01gxx-2000",
            "records": [{"Id": "00Q1"}],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["salesforce_soql_query"](query="SELECT Id FROM Lead")

        assert result["done"] is False
        assert result["next_records_url"] == "/services/data/v62.0/query/01gxx-2000"


class TestSalesforceGetRecord:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["salesforce_get_record"](object_type="", record_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "Id": "003xx000001",
            "FirstName": "Jane",
            "LastName": "Doe",
            "Email": "jane@example.com",
            "attributes": {"type": "Contact"},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["salesforce_get_record"](
                object_type="Contact", record_id="003xx000001"
            )

        assert result["Id"] == "003xx000001"
        assert result["Email"] == "jane@example.com"


class TestSalesforceCreateRecord:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["salesforce_create_record"](object_type="Lead", fields={})
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {"id": "00Qxx000001", "success": True, "errors": []}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["salesforce_create_record"](
                object_type="Lead",
                fields={"LastName": "Doe", "Company": "Acme"},
            )

        assert result["success"] is True
        assert result["id"] == "00Qxx000001"


class TestSalesforceUpdateRecord:
    def test_successful_update(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 204
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.patch", return_value=resp
            ),
        ):
            result = tool_fns["salesforce_update_record"](
                object_type="Lead",
                record_id="00Qxx000001",
                fields={"Status": "Contacted"},
            )

        assert result["success"] is True


class TestSalesforceDescribeObject:
    def test_successful_describe(self, tool_fns):
        data = {
            "name": "Lead",
            "label": "Lead",
            "keyPrefix": "00Q",
            "createable": True,
            "updateable": True,
            "fields": [
                {
                    "name": "Status",
                    "label": "Lead Status",
                    "type": "picklist",
                    "nillable": False,
                    "createable": True,
                    "picklistValues": [
                        {"value": "Open", "active": True},
                        {"value": "Closed", "active": True},
                    ],
                },
                {
                    "name": "Email",
                    "label": "Email",
                    "type": "email",
                    "nillable": True,
                    "createable": True,
                    "picklistValues": [],
                },
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["salesforce_describe_object"](object_type="Lead")

        assert result["name"] == "Lead"
        assert result["field_count"] == 2
        assert result["fields"][0]["picklist_values"] == ["Open", "Closed"]


class TestSalesforceListObjects:
    def test_successful_list(self, tool_fns):
        data = {
            "sobjects": [
                {
                    "name": "Lead",
                    "label": "Lead",
                    "keyPrefix": "00Q",
                    "queryable": True,
                    "createable": True,
                    "custom": False,
                },
                {
                    "name": "Account",
                    "label": "Account",
                    "keyPrefix": "001",
                    "queryable": True,
                    "createable": True,
                    "custom": False,
                },
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["salesforce_list_objects"]()

        assert result["count"] == 2
        assert result["sobjects"][0]["name"] == "Lead"
