"""Tests for plaid_tool - Plaid banking & financial data operations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.plaid_tool.plaid_tool import register_tools

ENV = {"PLAID_CLIENT_ID": "test-client-id", "PLAID_SECRET": "test-secret", "PLAID_ENV": "sandbox"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPlaidGetAccounts:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["plaid_get_accounts"](access_token="tok")
        assert "error" in result

    def test_missing_access_token(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_get_accounts"](access_token="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accounts": [
                {
                    "account_id": "acc-1",
                    "name": "Checking",
                    "official_name": "Primary Checking",
                    "type": "depository",
                    "subtype": "checking",
                    "mask": "1234",
                    "balances": {
                        "available": 1000.50,
                        "current": 1100.00,
                        "iso_currency_code": "USD",
                    },
                }
            ],
            "request_id": "req-1",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_get_accounts"](access_token="access-sandbox-123")

        assert len(result["accounts"]) == 1
        assert result["accounts"][0]["name"] == "Checking"
        assert result["accounts"][0]["available_balance"] == 1000.50


class TestPlaidGetBalance:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_get_balance"](access_token="")
        assert "error" in result

    def test_successful_balance(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accounts": [
                {
                    "account_id": "acc-1",
                    "name": "Savings",
                    "type": "depository",
                    "balances": {
                        "available": 5000,
                        "current": 5000,
                        "limit": None,
                        "iso_currency_code": "USD",
                    },
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_get_balance"](access_token="access-sandbox-123")

        assert result["accounts"][0]["available"] == 5000


class TestPlaidSyncTransactions:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_sync_transactions"](access_token="")
        assert "error" in result

    def test_successful_sync(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "added": [
                {
                    "transaction_id": "txn-1",
                    "account_id": "acc-1",
                    "amount": 42.50,
                    "date": "2024-01-15",
                    "name": "Coffee Shop",
                    "merchant_name": "Starbucks",
                    "category": ["Food and Drink"],
                    "pending": False,
                    "iso_currency_code": "USD",
                }
            ],
            "modified": [],
            "removed": [],
            "next_cursor": "cursor-abc",
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_sync_transactions"](access_token="access-sandbox-123")

        assert len(result["added"]) == 1
        assert result["added"][0]["amount"] == 42.50
        assert result["next_cursor"] == "cursor-abc"


class TestPlaidGetTransactions:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_get_transactions"](access_token="", start_date="", end_date="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "transactions": [
                {
                    "transaction_id": "txn-1",
                    "account_id": "acc-1",
                    "amount": 25.00,
                    "date": "2024-01-10",
                    "name": "Grocery Store",
                    "merchant_name": "Whole Foods",
                    "category": ["Shops", "Groceries"],
                    "pending": False,
                    "iso_currency_code": "USD",
                }
            ],
            "total_transactions": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_get_transactions"](
                access_token="access-sandbox-123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        assert len(result["transactions"]) == 1
        assert result["total_transactions"] == 1


class TestPlaidGetInstitution:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_get_institution"](institution_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "institution": {
                "institution_id": "ins_1",
                "name": "Bank of America",
                "products": ["transactions", "auth", "balance"],
                "country_codes": ["US"],
                "url": "https://www.bankofamerica.com",
                "logo": None,
                "oauth": True,
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_get_institution"](institution_id="ins_1")

        assert result["name"] == "Bank of America"
        assert result["oauth"] is True


class TestPlaidSearchInstitutions:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["plaid_search_institutions"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "institutions": [
                {
                    "institution_id": "ins_1",
                    "name": "Chase",
                    "products": ["transactions"],
                    "country_codes": ["US"],
                    "url": "https://www.chase.com",
                    "oauth": False,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.plaid_tool.plaid_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["plaid_search_institutions"](query="Chase")

        assert len(result["institutions"]) == 1
        assert result["institutions"][0]["name"] == "Chase"
