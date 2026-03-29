"""Tests for sap_tool - SAP S/4HANA Cloud read-only procurement data."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.sap_tool.sap_tool import register_tools

ENV = {
    "SAP_BASE_URL": "https://my-tenant-api.s4hana.ondemand.com",
    "SAP_USERNAME": "COMM_USER",
    "SAP_PASSWORD": "test-password",
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


class TestSAPListPurchaseOrders:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["sap_list_purchase_orders"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "d": {
                "__count": "1",
                "results": [
                    {
                        "PurchaseOrder": "4500000001",
                        "PurchaseOrderType": "NB",
                        "CompanyCode": "1010",
                        "Supplier": "17300001",
                        "CreationDate": "/Date(1672531200000)/",
                        "PurchaseOrderNetAmount": "15000.00",
                        "DocumentCurrency": "USD",
                    }
                ],
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.sap_tool.sap_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["sap_list_purchase_orders"]()

        assert result["count"] == 1
        assert result["total"] == 1
        assert result["purchase_orders"][0]["purchase_order"] == "4500000001"
        assert result["purchase_orders"][0]["net_amount"] == "15000.00"


class TestSAPGetPurchaseOrder:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["sap_get_purchase_order"](purchase_order="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "d": {
                "PurchaseOrder": "4500000001",
                "PurchaseOrderType": "NB",
                "CompanyCode": "1010",
                "Supplier": "17300001",
                "PurchasingOrganization": "1010",
                "CreationDate": "/Date(1672531200000)/",
                "PurchaseOrderNetAmount": "15000.00",
                "DocumentCurrency": "USD",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.sap_tool.sap_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["sap_get_purchase_order"](purchase_order="4500000001")

        assert result["purchase_order"] == "4500000001"
        assert result["purchasing_org"] == "1010"


class TestSAPListBusinessPartners:
    def test_successful_list(self, tool_fns):
        data = {
            "d": {
                "__count": "1",
                "results": [
                    {
                        "BusinessPartner": "1000000",
                        "BusinessPartnerCategory": "1",
                        "BusinessPartnerFullName": "Acme Corp",
                        "Customer": "CUST001",
                        "Supplier": "",
                        "CreationDate": "/Date(1672531200000)/",
                    }
                ],
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.sap_tool.sap_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["sap_list_business_partners"]()

        assert result["count"] == 1
        assert result["business_partners"][0]["name"] == "Acme Corp"
        assert result["business_partners"][0]["is_customer"] is True
        assert result["business_partners"][0]["is_supplier"] is False


class TestSAPListProducts:
    def test_successful_list(self, tool_fns):
        data = {
            "d": {
                "__count": "1",
                "results": [
                    {
                        "Product": "FG001",
                        "ProductType": "FERT",
                        "BaseUnit": "EA",
                        "ProductGroup": "001",
                        "CreationDate": "/Date(1672531200000)/",
                    }
                ],
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.sap_tool.sap_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["sap_list_products"]()

        assert result["count"] == 1
        assert result["products"][0]["product"] == "FG001"
        assert result["products"][0]["product_type"] == "FERT"


class TestSAPListSalesOrders:
    def test_successful_list(self, tool_fns):
        data = {
            "d": {
                "__count": "1",
                "results": [
                    {
                        "SalesOrder": "1",
                        "SalesOrderType": "OR",
                        "SalesOrganization": "1010",
                        "SoldToParty": "CUST001",
                        "CreationDate": "/Date(1672531200000)/",
                        "TotalNetAmount": "25000.00",
                        "TransactionCurrency": "USD",
                    }
                ],
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.sap_tool.sap_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["sap_list_sales_orders"]()

        assert result["count"] == 1
        assert result["sales_orders"][0]["sales_order"] == "1"
        assert result["sales_orders"][0]["net_amount"] == "25000.00"
