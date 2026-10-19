"""Tests for HubSpot CRM tool with FastMCP.

Covers:
- Credential handling (credential store, env var, missing)
- _HubSpotClient methods (search, get, create, update, delete, associations)
- HTTP error handling (401, 403, 404, 429, 500, timeout)
- All 12 MCP tool functions via register_tools
- Input validation (delete_object object_type whitelist)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.hubspot_tool.hubspot_tool import (
    HUBSPOT_API_BASE,
    _HubSpotClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def client():
    """Create a _HubSpotClient with a test token."""
    return _HubSpotClient("test-token")


def _register(mcp, credentials=None):
    """Helper to register tools and return the tool lookup dict."""
    register_tools(mcp, credentials=credentials)
    return mcp._tool_manager._tools


def _tool_fn(mcp, name, credentials=None):
    """Register tools and return a single tool function by name."""
    tools = _register(mcp, credentials)
    return tools[name].fn


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# _HubSpotClient unit tests
# ---------------------------------------------------------------------------


class TestHubSpotClientHeaders:
    """Verify client sends correct auth headers."""

    def test_headers_contain_bearer_token(self, client):
        headers = client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"


class TestHubSpotClientHandleResponse:
    """Verify _handle_response maps HTTP codes to error dicts."""

    @pytest.mark.parametrize(
        "status_code,expected_substr",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_known_error_codes(self, client, status_code, expected_substr):
        resp = _mock_response(status_code=status_code)
        result = client._handle_response(resp)
        assert "error" in result
        assert expected_substr in result["error"]

    def test_generic_4xx_with_json_message(self, client):
        resp = _mock_response(
            status_code=422,
            json_data={"message": "Property not found"},
        )
        result = client._handle_response(resp)
        assert "error" in result
        assert "422" in result["error"]
        assert "Property not found" in result["error"]

    def test_generic_5xx_fallback_to_text(self, client):
        resp = _mock_response(status_code=500, text="Internal Server Error")
        resp.json.side_effect = Exception("not json")
        result = client._handle_response(resp)
        assert "error" in result
        assert "500" in result["error"]

    def test_success_returns_json(self, client):
        resp = _mock_response(status_code=200, json_data={"id": "123"})
        result = client._handle_response(resp)
        assert result == {"id": "123"}


class TestHubSpotClientSearchObjects:
    """Tests for _HubSpotClient.search_objects."""

    def test_search_posts_correct_url(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": [], "total": 0})
            client.search_objects("contacts", query="test@example.com")
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/search"

    def test_search_sends_query_and_properties(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": []})
            client.search_objects(
                "contacts",
                query="jane",
                properties=["email", "firstname"],
                limit=5,
            )
            body = mock_post.call_args.kwargs["json"]
            assert body["query"] == "jane"
            assert body["properties"] == ["email", "firstname"]
            assert body["limit"] == 5

    def test_search_clamps_limit_to_100(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": []})
            client.search_objects("contacts", limit=999)
            body = mock_post.call_args.kwargs["json"]
            assert body["limit"] == 100


class TestHubSpotClientGetObject:
    """Tests for _HubSpotClient.get_object."""

    def test_get_object_url(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "42"})
            client.get_object("contacts", "42")
            args, _ = mock_get.call_args
            assert args[0] == f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/42"

    def test_get_object_passes_properties(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "42"})
            client.get_object("contacts", "42", properties=["email", "phone"])
            params = mock_get.call_args.kwargs["params"]
            assert params["properties"] == "email,phone"


class TestHubSpotClientCreateObject:
    """Tests for _HubSpotClient.create_object."""

    def test_create_object_posts_properties(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "99", "properties": {"email": "a@b.com"}})
            result = client.create_object("contacts", {"email": "a@b.com", "firstname": "Alice"})
            body = mock_post.call_args.kwargs["json"]
            assert body == {"properties": {"email": "a@b.com", "firstname": "Alice"}}
            assert result["id"] == "99"


class TestHubSpotClientUpdateObject:
    """Tests for _HubSpotClient.update_object."""

    def test_update_object_uses_patch(self, client):
        with patch("httpx.patch") as mock_patch:
            mock_patch.return_value = _mock_response(200, {"id": "42"})
            client.update_object("contacts", "42", {"phone": "+1234567890"})
            mock_patch.assert_called_once()
            args, kwargs = mock_patch.call_args
            assert "/contacts/42" in args[0]
            assert kwargs["json"] == {"properties": {"phone": "+1234567890"}}


class TestHubSpotClientDeleteObject:
    """Tests for _HubSpotClient.delete_object."""

    def test_delete_returns_status_on_204(self, client):
        with patch("httpx.delete") as mock_delete:
            mock_delete.return_value = _mock_response(status_code=204)
            result = client.delete_object("contacts", "42")
            assert result["status"] == "deleted"
            assert result["object_id"] == "42"

    def test_delete_non_204_delegates_to_handle_response(self, client):
        with patch("httpx.delete") as mock_delete:
            mock_delete.return_value = _mock_response(status_code=404, json_data={"message": "Not found"})
            result = client.delete_object("contacts", "42")
            assert "error" in result


class TestHubSpotClientAssociations:
    """Tests for association-related client methods."""

    def test_list_associations_url(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"results": []})
            client.list_associations("contacts", "1", "companies")
            args, _ = mock_get.call_args
            assert "/crm/v4/objects/contacts/1/associations/companies" in args[0]

    def test_list_associations_clamps_limit(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"results": []})
            client.list_associations("contacts", "1", "companies", limit=999)
            params = mock_get.call_args.kwargs["params"]
            assert params["limit"] == 500

    def test_create_association_uses_put(self, client):
        with patch("httpx.put") as mock_put:
            mock_put.return_value = _mock_response(200, {"status": "ok"})
            client.create_association("contacts", "1", "companies", "2")
            mock_put.assert_called_once()
            body = mock_put.call_args.kwargs["json"]
            assert body[0]["associationCategory"] == "HUBSPOT_DEFINED"


# ---------------------------------------------------------------------------
# Credential handling via register_tools
# ---------------------------------------------------------------------------


class TestHubSpotCredentials:
    """Tests for credential resolution in MCP tool functions."""

    def test_no_credentials_returns_error(self, mcp, monkeypatch):
        monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
        fn = _tool_fn(mcp, "hubspot_search_contacts")
        result = fn()
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_env_var_credential(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "env-token")
        fn = _tool_fn(mcp, "hubspot_search_contacts")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": []})
            fn(query="test")
            headers = mock_post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer env-token"

    def test_credential_store_used_when_provided(self, mcp):
        creds = MagicMock()
        creds.get.return_value = "store-token"
        fn = _tool_fn(mcp, "hubspot_search_contacts", credentials=creds)
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": []})
            fn(query="test")
            creds.get.assert_called_once_with("hubspot")
            headers = mock_post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer store-token"

    def test_credential_store_non_string_raises(self, mcp):
        creds = MagicMock()
        creds.get.return_value = {"access_token": "bad"}
        fn = _tool_fn(mcp, "hubspot_search_contacts", credentials=creds)
        with pytest.raises(TypeError, match="Expected string"):
            fn(query="test")

    def test_credential_store_account_alias(self, mcp):
        creds = MagicMock()
        creds.get_by_alias.return_value = "alias-token"
        fn = _tool_fn(mcp, "hubspot_search_contacts", credentials=creds)
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": []})
            fn(query="test", account="my-account")
            creds.get_by_alias.assert_called_once_with("hubspot", "my-account")


# ---------------------------------------------------------------------------
# MCP tool function tests — Contacts
# ---------------------------------------------------------------------------


class TestHubSpotSearchContacts:
    """Tests for hubspot_search_contacts tool."""

    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_search_contacts")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": [{"id": "1"}], "total": 1})
            result = fn(query="jane")
            assert result["total"] == 1

    def test_timeout(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_search_contacts")
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            result = fn(query="jane")
            assert result == {"error": "Request timed out"}

    def test_network_error(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_search_contacts")
        with patch("httpx.post", side_effect=httpx.RequestError("dns fail")):
            result = fn(query="jane")
            assert "Network error" in result["error"]


class TestHubSpotGetContact:
    """Tests for hubspot_get_contact tool."""

    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_get_contact")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "42", "properties": {"email": "a@b.com"}})
            result = fn(contact_id="42")
            assert result["id"] == "42"

    def test_404(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_get_contact")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(status_code=404)
            result = fn(contact_id="999")
            assert "error" in result
            assert "not found" in result["error"]


class TestHubSpotCreateContact:
    """Tests for hubspot_create_contact tool."""

    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_create_contact")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "99", "properties": {"email": "new@example.com"}})
            result = fn(properties={"email": "new@example.com"})
            assert result["id"] == "99"


class TestHubSpotUpdateContact:
    """Tests for hubspot_update_contact tool."""

    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_update_contact")
        with patch("httpx.patch") as mock_patch:
            mock_patch.return_value = _mock_response(200, {"id": "42"})
            result = fn(contact_id="42", properties={"phone": "+1234567890"})
            assert result["id"] == "42"


# ---------------------------------------------------------------------------
# MCP tool function tests — Companies
# ---------------------------------------------------------------------------


class TestHubSpotSearchCompanies:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_search_companies")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": [{"id": "c1"}], "total": 1})
            result = fn(query="Acme")
            assert result["total"] == 1


class TestHubSpotGetCompany:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_get_company")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "c1", "properties": {"name": "Acme"}})
            result = fn(company_id="c1")
            assert result["id"] == "c1"


class TestHubSpotCreateCompany:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_create_company")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "c2", "properties": {"name": "NewCo"}})
            result = fn(properties={"name": "NewCo"})
            assert result["id"] == "c2"


class TestHubSpotUpdateCompany:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_update_company")
        with patch("httpx.patch") as mock_patch:
            mock_patch.return_value = _mock_response(200, {"id": "c1"})
            result = fn(company_id="c1", properties={"industry": "Finance"})
            assert result["id"] == "c1"


# ---------------------------------------------------------------------------
# MCP tool function tests — Deals
# ---------------------------------------------------------------------------


class TestHubSpotSearchDeals:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_search_deals")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"results": [{"id": "d1"}], "total": 1})
            result = fn(query="big deal")
            assert result["total"] == 1


class TestHubSpotGetDeal:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_get_deal")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "d1", "properties": {"dealname": "Big Deal"}})
            result = fn(deal_id="d1")
            assert result["id"] == "d1"


class TestHubSpotCreateDeal:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_create_deal")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "d2", "properties": {"dealname": "New Deal"}})
            result = fn(properties={"dealname": "New Deal", "amount": "10000"})
            assert result["id"] == "d2"


class TestHubSpotUpdateDeal:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_update_deal")
        with patch("httpx.patch") as mock_patch:
            mock_patch.return_value = _mock_response(200, {"id": "d1"})
            result = fn(deal_id="d1", properties={"amount": "15000"})
            assert result["id"] == "d1"


# ---------------------------------------------------------------------------
# MCP tool function tests — Delete
# ---------------------------------------------------------------------------


class TestHubSpotDeleteObject:
    """Tests for hubspot_delete_object tool."""

    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_delete_object")
        with patch("httpx.delete") as mock_delete:
            mock_delete.return_value = _mock_response(status_code=204)
            result = fn(object_type="contacts", object_id="42")
            assert result["status"] == "deleted"

    def test_invalid_object_type(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_delete_object")
        result = fn(object_type="tickets", object_id="1")
        assert "error" in result
        assert "Unsupported object_type" in result["error"]

    @pytest.mark.parametrize("valid_type", ["contacts", "companies", "deals"])
    def test_all_valid_object_types(self, mcp, monkeypatch, valid_type):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_delete_object")
        with patch("httpx.delete") as mock_delete:
            mock_delete.return_value = _mock_response(status_code=204)
            result = fn(object_type=valid_type, object_id="1")
            assert result["status"] == "deleted"

    def test_timeout(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_delete_object")
        with patch("httpx.delete", side_effect=httpx.TimeoutException("t")):
            result = fn(object_type="contacts", object_id="1")
            assert result == {"error": "Request timed out"}


# ---------------------------------------------------------------------------
# MCP tool function tests — Associations
# ---------------------------------------------------------------------------


class TestHubSpotListAssociations:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_list_associations")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"results": [{"toObjectId": "c1"}]})
            result = fn(
                from_object_type="contacts",
                from_object_id="1",
                to_object_type="companies",
            )
            assert "results" in result

    def test_timeout(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_list_associations")
        with patch("httpx.get", side_effect=httpx.TimeoutException("t")):
            result = fn(
                from_object_type="contacts",
                from_object_id="1",
                to_object_type="companies",
            )
            assert result == {"error": "Request timed out"}


class TestHubSpotCreateAssociation:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "hubspot_create_association")
        with patch("httpx.put") as mock_put:
            mock_put.return_value = _mock_response(200, {"status": "ok"})
            result = fn(
                from_object_type="contacts",
                from_object_id="1",
                to_object_type="companies",
                to_object_id="2",
            )
            assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all 12 HubSpot tools are registered."""

    EXPECTED_TOOLS = [
        "hubspot_search_contacts",
        "hubspot_get_contact",
        "hubspot_create_contact",
        "hubspot_update_contact",
        "hubspot_search_companies",
        "hubspot_get_company",
        "hubspot_create_company",
        "hubspot_update_company",
        "hubspot_search_deals",
        "hubspot_get_deal",
        "hubspot_create_deal",
        "hubspot_update_deal",
        "hubspot_delete_object",
        "hubspot_list_associations",
        "hubspot_create_association",
    ]

    def test_all_tools_registered(self, mcp):
        tools = _register(mcp)
        for name in self.EXPECTED_TOOLS:
            assert name in tools, f"Tool {name} not registered"

    def test_tool_count(self, mcp):
        tools = _register(mcp)
        # Filter to only hubspot tools
        hubspot_tools = [k for k in tools if k.startswith("hubspot_")]
        assert len(hubspot_tools) == len(self.EXPECTED_TOOLS)
