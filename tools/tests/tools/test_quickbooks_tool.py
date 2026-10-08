"""Tests for quickbooks_tool - Accounting API operations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.quickbooks_tool.quickbooks_tool import register_tools

ENV = {
    "QUICKBOOKS_ACCESS_TOKEN": "test-oauth-token",
    "QUICKBOOKS_REALM_ID": "123456789",
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


class TestQuickbooksQuery:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["quickbooks_query"](entity="Customer")
        assert "error" in result

    def test_missing_entity(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["quickbooks_query"](entity="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        data = {
            "QueryResponse": {
                "Customer": [
                    {"Id": "1", "DisplayName": "ABC Corp", "Balance": 1250.00},
                    {"Id": "2", "DisplayName": "XYZ Inc", "Balance": 500.00},
                ],
                "totalCount": 2,
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.quickbooks_tool.quickbooks_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["quickbooks_query"](entity="Customer")

        assert result["count"] == 2
        assert result["entities"][0]["DisplayName"] == "ABC Corp"


class TestQuickbooksGetEntity:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["quickbooks_get_entity"](entity="", entity_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "Customer": {
                "Id": "1",
                "DisplayName": "ABC Corp",
                "Balance": 1250.00,
                "SyncToken": "0",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.quickbooks_tool.quickbooks_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["quickbooks_get_entity"](entity="Customer", entity_id="1")

        assert result["DisplayName"] == "ABC Corp"
        assert result["Balance"] == 1250.00


class TestQuickbooksCreateCustomer:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["quickbooks_create_customer"](display_name="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "Customer": {
                "Id": "59",
                "DisplayName": "New Customer",
                "SyncToken": "0",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.quickbooks_tool.quickbooks_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["quickbooks_create_customer"](display_name="New Customer", email="new@example.com")

        assert result["result"] == "created"
        assert result["id"] == "59"


class TestQuickbooksCreateInvoice:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["quickbooks_create_invoice"](customer_id="", line_items="")
        assert "error" in result

    def test_invalid_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["quickbooks_create_invoice"](customer_id="1", line_items="not json")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "Invoice": {
                "Id": "130",
                "DocNumber": "1001",
                "TotalAmt": 100.00,
                "Balance": 100.00,
                "SyncToken": "0",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.quickbooks_tool.quickbooks_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["quickbooks_create_invoice"](
                customer_id="1",
                line_items='[{"description": "Consulting", "amount": 100.00, "item_id": "1"}]',
            )

        assert result["result"] == "created"
        assert result["id"] == "130"
        assert result["total_amt"] == 100.00


class TestQuickbooksGetCompanyInfo:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["quickbooks_get_company_info"]()
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "CompanyInfo": {
                "CompanyName": "My Company",
                "LegalName": "My Company LLC",
                "Country": "US",
                "Email": {"Address": "info@mycompany.com"},
                "FiscalYearStartMonth": "January",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.quickbooks_tool.quickbooks_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["quickbooks_get_company_info"]()

        assert result["company_name"] == "My Company"
        assert result["email"] == "info@mycompany.com"
