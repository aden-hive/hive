"""
Tests for HubSpot CRM tool and OAuth2 provider.

Covers:
- _HubSpotClient methods (search, get, create, update)
- Error handling (401, 403, 404, 429, 500, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 12 MCP tool functions
- HubSpotOAuth2Provider configuration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.hubspot_tool.hubspot_tool import (
    HUBSPOT_API_BASE,
    _HubSpotClient,
    register_tools,
)

# --- _HubSpotClient tests ---


class TestHubSpotClient:
    def setup_method(self):
        self.client = _HubSpotClient("test-token")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": []}
        assert self.client._handle_response(response) == {"results": []}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"message": "Internal Server Error"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_objects(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 1,
            "results": [{"id": "1", "properties": {"email": "test@example.com"}}],
        }
        mock_post.return_value = mock_response

        result = self.client.search_objects("contacts", query="test", properties=["email"], limit=5)

        mock_post.assert_called_once_with(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/search",
            headers=self.client._headers,
            json={"limit": 5, "query": "test", "properties": ["email"]},
            timeout=30.0,
        )
        assert result["total"] == 1

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_objects_no_query(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "results": []}
        mock_post.return_value = mock_response

        self.client.search_objects("contacts", limit=10)

        call_json = mock_post.call_args.kwargs["json"]
        assert "query" not in call_json
        assert call_json["limit"] == 10

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_objects_limit_capped(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "results": []}
        mock_post.return_value = mock_response

        self.client.search_objects("contacts", limit=200)

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["limit"] == 100

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_object(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "123", "properties": {"email": "test@example.com"}}
        mock_get.return_value = mock_response

        result = self.client.get_object("contacts", "123", properties=["email"])

        mock_get.assert_called_once_with(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/123",
            headers=self.client._headers,
            params={"properties": "email"},
            timeout=30.0,
        )
        assert result["id"] == "123"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_object_no_properties(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "123"}
        mock_get.return_value = mock_response

        self.client.get_object("contacts", "123")

        assert mock_get.call_args.kwargs["params"] == {}

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_create_object(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "456",
            "properties": {"email": "new@example.com", "firstname": "Jane"},
        }
        mock_post.return_value = mock_response

        result = self.client.create_object(
            "contacts", {"email": "new@example.com", "firstname": "Jane"}
        )

        mock_post.assert_called_once_with(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts",
            headers=self.client._headers,
            json={"properties": {"email": "new@example.com", "firstname": "Jane"}},
            timeout=30.0,
        )
        assert result["id"] == "456"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.patch")
    def test_update_object(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "123", "properties": {"phone": "+1234567890"}}
        mock_patch.return_value = mock_response

        result = self.client.update_object("contacts", "123", {"phone": "+1234567890"})

        mock_patch.assert_called_once_with(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/123",
            headers=self.client._headers,
            json={"properties": {"phone": "+1234567890"}},
            timeout=30.0,
        )
        assert result["id"] == "123"


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def _get_tool_fn(self, mcp_mock, tool_name):
        """Extract a registered tool function by name from mcp.tool() calls."""
        for call in mcp_mock.tool.return_value.call_args_list:
            fn = call[0][0]
            if fn.__name__ == tool_name:
                return fn
        raise ValueError(f"Tool '{tool_name}' not found in registered tools")

    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 12

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        # Pick the first tool and call it
        search_fn = next(fn for fn in registered_fns if fn.__name__ == "hubspot_search_contacts")
        result = search_fn()
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "test-token"

        register_tools(mcp, credentials=cred_manager)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "hubspot_search_contacts")

        with patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"total": 0, "results": []}
            mock_post.return_value = mock_response

            result = search_fn(query="test")

        cred_manager.get.assert_called_with("hubspot")
        assert result["total"] == 0

    def test_credentials_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "hubspot_search_contacts")

        with (
            patch.dict("os.environ", {"HUBSPOT_ACCESS_TOKEN": "env-token"}),
            patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post") as mock_post,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"total": 0, "results": []}
            mock_post.return_value = mock_response

            result = search_fn(query="test")

        assert result["total"] == 0
        # Verify the token was used in headers
        call_headers = mock_post.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer env-token"


# --- Individual tool function tests ---


class TestContactTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_contacts(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"total": 1, "results": [{"id": "1"}]})
        )
        result = self._fn("hubspot_search_contacts")(query="john")
        assert result["total"] == 1

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_contact(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"id": "1"}))
        result = self._fn("hubspot_get_contact")(contact_id="1")
        assert result["id"] == "1"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_create_contact(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=201, json=MagicMock(return_value={"id": "2"})
        )
        result = self._fn("hubspot_create_contact")(properties={"email": "a@b.com"})
        assert result["id"] == "2"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.patch")
    def test_update_contact(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "1"})
        )
        result = self._fn("hubspot_update_contact")(contact_id="1", properties={"phone": "123"})
        assert result["id"] == "1"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_contacts_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("hubspot_search_contacts")(query="test")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_contact_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn("hubspot_get_contact")(contact_id="1")
        assert "error" in result
        assert "Network error" in result["error"]


class TestCompanyTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_companies(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"total": 2, "results": []})
        )
        result = self._fn("hubspot_search_companies")(query="acme")
        assert result["total"] == 2

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_company(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "10"})
        )
        result = self._fn("hubspot_get_company")(company_id="10")
        assert result["id"] == "10"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_create_company(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=201, json=MagicMock(return_value={"id": "11"})
        )
        result = self._fn("hubspot_create_company")(properties={"name": "Acme"})
        assert result["id"] == "11"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.patch")
    def test_update_company(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "10"})
        )
        result = self._fn("hubspot_update_company")(
            company_id="10", properties={"industry": "Tech"}
        )
        assert result["id"] == "10"


class TestDealTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_search_deals(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"total": 3, "results": []})
        )
        result = self._fn("hubspot_search_deals")(query="big deal")
        assert result["total"] == 3

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.get")
    def test_get_deal(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "20"})
        )
        result = self._fn("hubspot_get_deal")(deal_id="20")
        assert result["id"] == "20"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.post")
    def test_create_deal(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=201, json=MagicMock(return_value={"id": "21"})
        )
        result = self._fn("hubspot_create_deal")(properties={"dealname": "New Deal"})
        assert result["id"] == "21"

    @patch("aden_tools.tools.hubspot_tool.hubspot_tool.httpx.patch")
    def test_update_deal(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "20"})
        )
        result = self._fn("hubspot_update_deal")(deal_id="20", properties={"amount": "5000"})
        assert result["id"] == "20"


# --- HubSpotOAuth2Provider tests ---


class TestHubSpotOAuth2Provider:
    def test_provider_id(self):
        from framework.credentials.oauth2.hubspot_provider import HubSpotOAuth2Provider

        provider = HubSpotOAuth2Provider(client_id="cid", client_secret="csecret")
        assert provider.provider_id == "hubspot_oauth2"

    def test_default_scopes(self):
        from framework.credentials.oauth2.hubspot_provider import (
            HUBSPOT_DEFAULT_SCOPES,
            HubSpotOAuth2Provider,
        )

        provider = HubSpotOAuth2Provider(client_id="cid", client_secret="csecret")
        assert provider.config.default_scopes == HUBSPOT_DEFAULT_SCOPES

    def test_custom_scopes(self):
        from framework.credentials.oauth2.hubspot_provider import HubSpotOAuth2Provider

        provider = HubSpotOAuth2Provider(
            client_id="cid",
            client_secret="csecret",
            scopes=["crm.objects.contacts.read"],
        )
        assert provider.config.default_scopes == ["crm.objects.contacts.read"]

    def test_endpoints(self):
        from framework.credentials.oauth2.hubspot_provider import (
            HUBSPOT_AUTHORIZATION_URL,
            HUBSPOT_TOKEN_URL,
            HubSpotOAuth2Provider,
        )

        provider = HubSpotOAuth2Provider(client_id="cid", client_secret="csecret")
        assert provider.config.token_url == HUBSPOT_TOKEN_URL
        assert provider.config.authorization_url == HUBSPOT_AUTHORIZATION_URL

    def test_supported_types(self):
        from framework.credentials.models import CredentialType
        from framework.credentials.oauth2.hubspot_provider import HubSpotOAuth2Provider

        provider = HubSpotOAuth2Provider(client_id="cid", client_secret="csecret")
        assert CredentialType.OAUTH2 in provider.supported_types

    def test_validate_no_access_token(self):
        from framework.credentials.models import CredentialObject
        from framework.credentials.oauth2.hubspot_provider import HubSpotOAuth2Provider

        provider = HubSpotOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="test")
        assert provider.validate(cred) is False


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_hubspot_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "hubspot" in CREDENTIAL_SPECS

    def test_hubspot_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["hubspot"]
        assert spec.env_var == "HUBSPOT_ACCESS_TOKEN"

    def test_hubspot_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["hubspot"]
        assert "hubspot_search_contacts" in spec.tools
        assert "hubspot_create_deal" in spec.tools
        assert len(spec.tools) == 12
