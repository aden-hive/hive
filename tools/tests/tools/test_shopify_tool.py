"""Tests for shopify_tool - Shopify Admin REST API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.shopify_tool.shopify_tool import register_tools

ENV = {
    "SHOPIFY_ACCESS_TOKEN": "shpat_test_token_123",
    "SHOPIFY_STORE_NAME": "my-test-store",
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


class TestShopifyListOrders:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["shopify_list_orders"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "orders": [
                {
                    "id": 450789469,
                    "name": "#1001",
                    "email": "bob@example.com",
                    "created_at": "2025-01-10T11:00:00-05:00",
                    "financial_status": "paid",
                    "fulfillment_status": None,
                    "total_price": "199.00",
                    "currency": "USD",
                    "line_items": [{"id": 1, "title": "Widget"}],
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_list_orders"]()

        assert result["count"] == 1
        assert result["orders"][0]["id"] == 450789469
        assert result["orders"][0]["total_price"] == "199.00"
        assert result["orders"][0]["line_item_count"] == 1


class TestShopifyGetOrder:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["shopify_get_order"](order_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "order": {
                "id": 450789469,
                "name": "#1001",
                "email": "bob@example.com",
                "created_at": "2025-01-10T11:00:00-05:00",
                "updated_at": "2025-01-10T12:00:00-05:00",
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
                "total_price": "199.00",
                "subtotal_price": "189.00",
                "total_tax": "10.00",
                "currency": "USD",
                "line_items": [
                    {
                        "title": "Hiking Backpack",
                        "quantity": 1,
                        "price": "189.00",
                        "sku": "HB-001",
                        "variant_id": 39072856,
                        "product_id": 632910392,
                    }
                ],
                "shipping_address": {"city": "Ottawa"},
                "billing_address": {"city": "Ottawa"},
                "customer": {
                    "id": 207119551,
                    "email": "bob@example.com",
                    "first_name": "Bob",
                    "last_name": "Smith",
                },
                "note": "Rush order",
                "tags": "vip",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_get_order"](order_id="450789469")

        assert result["id"] == 450789469
        assert result["line_items"][0]["title"] == "Hiking Backpack"
        assert result["customer"]["first_name"] == "Bob"


class TestShopifyListProducts:
    def test_successful_list(self, tool_fns):
        data = {
            "products": [
                {
                    "id": 632910392,
                    "title": "Hiking Backpack",
                    "vendor": "TrailCo",
                    "product_type": "Outdoor Gear",
                    "status": "active",
                    "handle": "hiking-backpack",
                    "created_at": "2025-01-10T11:00:00-05:00",
                    "variants": [{"id": 1}, {"id": 2}],
                    "tags": "hiking, outdoor",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_list_products"]()

        assert result["count"] == 1
        assert result["products"][0]["title"] == "Hiking Backpack"
        assert result["products"][0]["variant_count"] == 2


class TestShopifyGetProduct:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["shopify_get_product"](product_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "product": {
                "id": 632910392,
                "title": "Hiking Backpack",
                "body_html": "<p>Durable backpack</p>",
                "vendor": "TrailCo",
                "product_type": "Outdoor Gear",
                "handle": "hiking-backpack",
                "status": "active",
                "created_at": "2025-01-10T11:00:00-05:00",
                "updated_at": "2025-01-10T12:00:00-05:00",
                "tags": "hiking, outdoor",
                "variants": [
                    {
                        "id": 39072856,
                        "title": "Large / Blue",
                        "price": "199.00",
                        "sku": "HB-LG-BL",
                        "inventory_quantity": 25,
                        "option1": "Large",
                        "option2": "Blue",
                        "option3": None,
                    }
                ],
                "options": [{"name": "Size"}, {"name": "Color"}],
                "images": [{"id": 850703190, "src": "https://cdn.shopify.com/test.jpg", "position": 1}],
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_get_product"](product_id="632910392")

        assert result["id"] == 632910392
        assert result["variants"][0]["price"] == "199.00"
        assert result["variants"][0]["sku"] == "HB-LG-BL"
        assert len(result["images"]) == 1


class TestShopifyListCustomers:
    def test_successful_list(self, tool_fns):
        data = {
            "customers": [
                {
                    "id": 207119551,
                    "first_name": "Bob",
                    "last_name": "Smith",
                    "email": "bob@example.com",
                    "phone": "+16135551234",
                    "orders_count": 5,
                    "total_spent": "995.00",
                    "state": "enabled",
                    "tags": "vip",
                    "created_at": "2025-01-10T11:00:00-05:00",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_list_customers"]()

        assert result["count"] == 1
        assert result["customers"][0]["email"] == "bob@example.com"
        assert result["customers"][0]["total_spent"] == "995.00"


class TestShopifySearchCustomers:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["shopify_search_customers"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "customers": [
                {
                    "id": 207119551,
                    "first_name": "Bob",
                    "last_name": "Smith",
                    "email": "bob@example.com",
                    "phone": "+16135551234",
                    "orders_count": 5,
                    "total_spent": "995.00",
                    "state": "enabled",
                    "tags": "vip",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.shopify_tool.shopify_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["shopify_search_customers"](query="email:bob@example.com")

        assert result["count"] == 1
        assert result["customers"][0]["first_name"] == "Bob"
