"""
Tests for Zoho CRM MCP tools and OAuth2 provider.

Covers:
- Tool registration and credential retrieval (CredentialStoreAdapter vs env)
- All 6 MCP tool functions (list_records, get_record, create_record,
  search_records, list_modules, add_note)
- Error handling (timeout, network error, missing params)
- ZohoOAuth2Provider configuration
- Credential spec
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from aden_tools.tools.zoho_crm_tool.zoho_crm_tool import register_tools

# --- Tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_six_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 6

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search_records")
        result = search_fn(module="Leads", word="Zoho")
        assert "error" in result
        assert "ZOHO_CRM_ACCESS_TOKEN" in result["error"]

    def test_credentials_from_adapter(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred = MagicMock()
        cred.get.return_value = "test-token"

        register_tools(mcp, credentials=cred)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search_records")

        with patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [{"id": "1"}], "info": {"page": 1}}),
            )
            result = search_fn(module="Leads", word="Zoho")

        cred.get.assert_any_call("zoho_crm")
        assert result["count"] == 1

    def test_credentials_from_env_ZOHO_CRM_ACCESS_TOKEN(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search_records")

        with (
            patch.dict("os.environ", {"ZOHO_CRM_ACCESS_TOKEN": "env-token"}),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [], "info": {"page": 1, "per_page": 2}}),
            )
            result = search_fn(module="Leads", word="Zoho")

        assert result["count"] == 0
        call_headers = mock_get.call_args.kwargs.get("headers") or mock_get.call_args[1].get("headers", {})
        assert call_headers["Authorization"] == "Zoho-oauthtoken env-token"


# --- Individual tool function tests ---


class TestZohoCRMTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_search_records_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": [{"id": "1", "First_Name": "Zoho"}],
                }
            ),
        )
        result = self._fn("zoho_crm_search_records")(module="Leads", word="Zoho")
        assert result["count"] == 1
        assert result["module"] == "Leads"
        assert "results" in result

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_list_records_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": [{"id": "1"}],
                    "info": {"page": 1, "count": 1, "more_records": False},
                }
            ),
        )
        result = self._fn("zoho_crm_list_records")(module="Leads")
        assert result["module"] == "Leads"
        assert "records" in result

    def test_zoho_crm_search_records_no_params(self):
        result = self._fn("zoho_crm_search_records")(module="Leads")
        assert "error" in result

    def test_zoho_crm_search_records_no_module(self):
        result = self._fn("zoho_crm_search_records")(module="", word="x")
        assert "error" in result

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_get_record_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"id": "123", "First_Name": "Jane"}]}),
        )
        result = self._fn("zoho_crm_get_record")(module="Leads", record_id="123")
        assert result["record"]["id"] == "123"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_zoho_crm_create_record_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": [{"details": {"id": "456"}, "status": "success", "message": "created"}]},
            ),
        )
        result = self._fn("zoho_crm_create_record")(
            module="Leads",
            record_data={"First_Name": "A", "Last_Name": "B", "Company": "C"},
        )
        assert result["id"] == "456"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_zoho_crm_add_note_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"details": {"id": "note-1"}, "status": "success"}]}),
        )
        result = self._fn("zoho_crm_add_note")(
            module="Leads",
            record_id="123",
            title="Test",
            content="Body",
        )
        assert result["id"] == "note-1"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_search_records_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("zoho_crm_search_records")(module="Leads", word="test")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_get_record_network_error(self, mock_get):
        mock_get.side_effect = Exception("connection failed")
        result = self._fn("zoho_crm_get_record")(module="Leads", record_id="1")
        assert "error" in result


# --- ZohoOAuth2Provider tests ---


class TestZohoOAuth2Provider:
    def test_provider_id(self):
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        assert provider.provider_id == "zoho_crm_oauth2"

    def test_default_scopes(self):
        from framework.credentials.oauth2.zoho_provider import (
            ZOHO_DEFAULT_SCOPES,
            ZohoOAuth2Provider,
        )

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        assert provider.config.default_scopes == ZOHO_DEFAULT_SCOPES

    def test_custom_scopes(self):
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(
            client_id="cid",
            client_secret="csecret",
            scopes=["ZohoCRM.modules.leads.ALL"],
        )
        assert provider.config.default_scopes == ["ZohoCRM.modules.leads.ALL"]

    def test_endpoints_region_aware(self):
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(
            client_id="cid",
            client_secret="csecret",
            accounts_domain="https://accounts.zoho.in",
        )
        assert "accounts.zoho.in" in provider.config.token_url
        assert "oauth/v2/token" in provider.config.token_url

    def test_supported_types(self):
        from framework.credentials.models import CredentialType
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        assert CredentialType.OAUTH2 in provider.supported_types

    def test_validate_no_access_token(self):
        from framework.credentials.models import CredentialObject
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="test")
        assert provider.validate(cred) is False

    def test_validate_success_200(self):
        from framework.credentials.models import CredentialObject
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="test")
        cred.set_key("access_token", "tok")

        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(status_code=200)
        with patch.object(provider, "_get_client", return_value=mock_client):
            assert provider.validate(cred) is True

    def test_validate_invalid_401(self):
        from framework.credentials.models import CredentialObject
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="test")
        cred.set_key("access_token", "tok")

        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(status_code=401)
        with patch.object(provider, "_get_client", return_value=mock_client):
            assert provider.validate(cred) is False

    def test_validate_rate_limited_429_still_valid(self):
        from framework.credentials.models import CredentialObject
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="test")
        cred.set_key("access_token", "tok")

        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(status_code=429)
        with patch.object(provider, "_get_client", return_value=mock_client):
            assert provider.validate(cred) is True

    def test_refresh_persists_dc_metadata(self):
        from framework.credentials.models import CredentialObject, CredentialType
        from framework.credentials.oauth2.provider import OAuth2Token
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        cred = CredentialObject(id="zoho_crm", credential_type=CredentialType.OAUTH2)
        cred.set_key("refresh_token", "rtok")

        token = OAuth2Token(access_token="atok", refresh_token="rtok")
        token.raw_response = {
            "api_domain": "https://www.zohoapis.in",
            "accounts-server": "https://accounts.zoho.in",
            "location": "in",
        }

        with patch.object(provider, "refresh_access_token", return_value=token):
            refreshed = provider.refresh(cred)

        assert refreshed.get_key("access_token") == "atok"
        assert refreshed.get_key("api_domain") == "https://www.zohoapis.in"
        assert refreshed.get_key("accounts_domain") == "https://accounts.zoho.in"
        assert refreshed.get_key("location") == "in"

    def test_format_for_request_custom_header(self):
        from framework.credentials.oauth2.provider import OAuth2Token
        from framework.credentials.oauth2.zoho_provider import ZohoOAuth2Provider

        provider = ZohoOAuth2Provider(client_id="cid", client_secret="csecret")
        token = OAuth2Token(access_token="abc123")
        out = provider.format_for_request(token)
        assert "headers" in out
        assert out["headers"]["Authorization"] == "Zoho-oauthtoken abc123"

    def test_tool_uses_stored_api_domain(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(mcp, credentials=cred)

        search_fn = next(fn for fn in fns if fn.__name__ == "zoho_crm_search_records")
        with (
            patch.dict("os.environ", {"ZOHO_CRM_DOMAIN": "www.zohoapis.in"}),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [], "info": {"page": 1, "per_page": 2}}),
            )
            search_fn(module="Leads", word="Zoho")

        called_url = mock_get.call_args.args[0]
        assert called_url.startswith("https://www.zohoapis.in/crm/v7/")


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_zoho_crm_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "zoho_crm" in CREDENTIAL_SPECS

    def test_zoho_crm_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["zoho_crm"]
        assert spec.env_var == "ZOHO_CRM_ACCESS_TOKEN"

    def test_zoho_crm_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["zoho_crm"]
        assert "zoho_crm_list_records" in spec.tools
        assert "zoho_crm_get_record" in spec.tools
        assert "zoho_crm_create_record" in spec.tools
        assert "zoho_crm_search_records" in spec.tools
        assert "zoho_crm_list_modules" in spec.tools
        assert "zoho_crm_add_note" in spec.tools
        assert len(spec.tools) == 6
