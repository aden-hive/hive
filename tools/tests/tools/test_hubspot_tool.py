"""Tests for hubspot_tool - HubSpot CRM contacts, companies, and deals."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.hubspot_tool.hubspot_tool import register_tools

ENV = {"HUBSPOT_ACCESS_TOKEN": "test-token-abc"}


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


class TestHubSpotMissingCredentials:
    def test_search_contacts_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["hubspot_search_contacts"]()
        assert "error" in result

    def test_get_contact_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["hubspot_get_contact"](contact_id="123")
        assert "error" in result

    def test_search_companies_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["hubspot_search_companies"]()
        assert "error" in result

    def test_search_deals_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["hubspot_search_deals"]()
        assert "error" in result


class TestHubSpotSearchContacts:
    def test_successful_search(self, tool_fns):
        data = {
            "results": [
                {"id": "1", "properties": {"firstname": "Alice", "email": "alice@example.com"}},
            ],
            "total": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["hubspot_search_contacts"](query="Alice")
        assert result["total"] == 1
        assert result["results"][0]["properties"]["firstname"] == "Alice"

    def test_rate_limit_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp({}, 429),
            ),
        ):
            result = tool_fns["hubspot_search_contacts"](query="test")
        assert "error" in result

    def test_unauthorized_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp({}, 401),
            ),
        ):
            result = tool_fns["hubspot_search_contacts"]()
        assert "error" in result


class TestHubSpotGetContact:
    def test_successful_get(self, tool_fns):
        data = {"id": "42", "properties": {"firstname": "Bob", "email": "bob@example.com"}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["hubspot_get_contact"](contact_id="42")
        assert result["id"] == "42"
        assert result["properties"]["email"] == "bob@example.com"

    def test_not_found_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get",
                return_value=_mock_resp({}, 404),
            ),
        ):
            result = tool_fns["hubspot_get_contact"](contact_id="999")
        assert "error" in result


class TestHubSpotCreateContact:
    def test_successful_create(self, tool_fns):
        data = {"id": "100", "properties": {"firstname": "Carol", "email": "carol@example.com"}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["hubspot_create_contact"](
                properties={"firstname": "Carol", "email": "carol@example.com"}
            )
        assert result["id"] == "100"


class TestHubSpotSearchDeals:
    def test_successful_search(self, tool_fns):
        data = {
            "results": [{"id": "d1", "properties": {"dealname": "Big Deal", "amount": "50000"}}],
            "total": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["hubspot_search_deals"](query="Big Deal")
        assert result["total"] == 1
        assert result["results"][0]["properties"]["dealname"] == "Big Deal"


class TestHubSpotSearchCompanies:
    def test_successful_search(self, tool_fns):
        data = {
            "results": [{"id": "c1", "properties": {"name": "Acme Corp", "domain": "acme.com"}}],
            "total": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["hubspot_search_companies"](query="Acme")
        assert result["total"] == 1
        assert result["results"][0]["properties"]["name"] == "Acme Corp"
