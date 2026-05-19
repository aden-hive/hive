"""
Tests for Zoho CRM tool and OAuth2 provider.

Covers:
- _ZohoCRMClient methods (search, get, create, update, add_note)
- Error handling (401, 403, 404, 429, timeout)
- Credential retrieval (CredentialStoreAdapter vs env vs exchange)
- All 5 MCP tool functions
- ZohoOAuth2Provider configuration
- Credential spec
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.zoho_crm_tool.zoho_crm_tool import (
    CRM_API_VERSION,
    _ZohoCRMClient,
    register_tools,
)

# --- _ZohoCRMClient tests ---


class TestZohoCRMClient:
    def setup_method(self):
        self.client = _ZohoCRMClient("test-token")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Zoho-oauthtoken test-token"
        assert headers["Content-Type"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": []}
        assert self.client._handle_response(response) == {"data": []}

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

    def test_handle_response_429_retriable(self):
        response = MagicMock()
        response.status_code = 429
        result = self.client._handle_response(response)
        assert result.get("retriable") is True

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"message": "Internal Server Error"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_search_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "1", "First_Name": "Zoho"}],
            "info": {"page": 1, "per_page": 2, "more_records": False},
        }
        mock_get.return_value = mock_response

        result = self.client.search_records("Leads", criteria="", word="Zoho", page=1, per_page=2)

        mock_get.assert_called_once()
        call_url = mock_get.call_args.args[0]
        assert f"/crm/{CRM_API_VERSION}/Leads/search" in call_url
        assert result["data"]
        assert result["info"]["page"] == 1

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_get_record(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "1192161000000585006"}]}
        mock_get.return_value = mock_response

        result = self.client.get_record("Leads", "1192161000000585006")

        mock_get.assert_called_once_with(
            f"{self.client._api_base}/Leads/1192161000000585006",
            headers=self.client._headers,
            timeout=30.0,
        )
        assert result["data"][0]["id"] == "1192161000000585006"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_create_record(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"details": {"id": "1192161000000586001"}}],
        }
        mock_post.return_value = mock_response

        data = {"First_Name": "Zoho", "Last_Name": "Test", "Company": "Hive"}
        result = self.client.create_record("Leads", data)

        mock_post.assert_called_once_with(
            f"{self.client._api_base}/Leads",
            headers=self.client._headers,
            json={"data": [data]},
            timeout=30.0,
        )
        assert result["data"][0]["details"]["id"] == "1192161000000586001"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.put")
    def test_update_record(self, mock_put):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"details": {"id": "1192161000000586001"}}]}
        mock_put.return_value = mock_response

        result = self.client.update_record(
            "Leads", "1192161000000586001", {"Description": "Updated"}
        )

        mock_put.assert_called_once_with(
            f"{self.client._api_base}/Leads/1192161000000586001",
            headers=self.client._headers,
            json={"data": [{"Description": "Updated"}]},
            timeout=30.0,
        )
        assert result["data"][0]["details"]["id"] == "1192161000000586001"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_add_note_parent_id_structure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"details": {"id": "note-1"}}]}
        mock_post.return_value = mock_response

        self.client.add_note("Leads", "1192161000000586001", "Title", "Content")

        call_json = mock_post.call_args.kwargs["json"]
        note_data = call_json["data"][0]
        assert note_data["Parent_Id"] == {
            "module": {"api_name": "Leads"},
            "id": "1192161000000586001",
        }
        assert note_data["Note_Title"] == "Title"
        assert note_data["Note_Content"] == "Content"


# --- Tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_five_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 5

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search")
        result = search_fn(module="Leads", word="Zoho")
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_adapter(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred = MagicMock()
        cred.get_key.return_value = "test-token"

        register_tools(mcp, credentials=cred)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search")

        with patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [], "info": {"page": 1, "per_page": 2}}),
            )
            result = search_fn(module="Leads", word="Zoho")

        cred.get_key.assert_any_call("zoho_crm", "access_token")
        assert result["success"] is True
        assert result["count"] == 0

    def test_credentials_from_env_ZOHO_ACCESS_TOKEN(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "zoho_crm_search")

        with (
            patch.dict("os.environ", {"ZOHO_ACCESS_TOKEN": "env-token"}),
            patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [], "info": {"page": 1, "per_page": 2}}),
            )
            result = search_fn(module="Leads", word="Zoho")

        assert result["success"] is True
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Zoho-oauthtoken env-token"


# --- Individual tool function tests ---


class TestZohoCRMTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get_key.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_search_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": [{"id": "1", "First_Name": "Zoho"}],
                    "info": {"page": 1, "per_page": 2, "more_records": False},
                }
            ),
        )
        result = self._fn("zoho_crm_search")(module="Leads", word="Zoho")
        assert result["success"] is True
        assert result["count"] == 1
        assert result["module"] == "Leads"
        assert result["next_page"] is None
        assert "data" in result
        assert "raw" in result

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_search_next_page(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": [{"id": "1"}],
                    "info": {"page": 2, "per_page": 200, "more_records": True},
                }
            ),
        )
        result = self._fn("zoho_crm_search")(module="Leads", criteria="(Email:equals:a@b.com)")
        assert result["next_page"] == 3

    def test_zoho_crm_search_invalid_module(self):
        result = self._fn("zoho_crm_search")(module="Invalid", word="x")
        assert "error" in result
        assert "Invalid module" in result["error"]

    def test_zoho_crm_search_no_word_or_criteria(self):
        result = self._fn("zoho_crm_search")(module="Leads")
        assert "error" in result
        assert "word" in result["error"] or "criteria" in result["error"]

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_get_record_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"id": "123", "First_Name": "Jane"}]}),
        )
        result = self._fn("zoho_crm_get_record")(module="Leads", id="123")
        assert result["success"] is True
        assert result["data"]["id"] == "123"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_zoho_crm_create_record_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": [{"details": {"id": "456"}}]},
            ),
        )
        result = self._fn("zoho_crm_create_record")(
            module="Leads",
            data={"First_Name": "A", "Last_Name": "B", "Company": "C"},
        )
        assert result["success"] is True
        assert result["id"] == "456"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.put")
    def test_zoho_crm_update_record_success(self, mock_put):
        mock_put.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"details": {"id": "123"}}]}),
        )
        result = self._fn("zoho_crm_update_record")(
            module="Leads", id="123", data={"Description": "Updated"}
        )
        assert result["success"] is True
        assert result["id"] == "123"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.post")
    def test_zoho_crm_add_note_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": [{"details": {"id": "note-1"}}]}),
        )
        result = self._fn("zoho_crm_add_note")(
            module="Leads",
            id="123",
            note_title="Test",
            note_content="Body",
        )
        assert result["success"] is True
        assert result["id"] == "note-1"
        assert result["data"]["parent_id"] == "123"

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_search_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("zoho_crm_search")(module="Leads", word="test")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get")
    def test_zoho_crm_get_record_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn("zoho_crm_get_record")(module="Leads", id="1")
        assert "error" in result
        assert "Network error" in result["error"]


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
        cred.get_key.side_effect = lambda cid, key: {
            "access_token": "tok",
            "api_domain": "https://www.zohoapis.in",
        }.get(key)
        register_tools(mcp, credentials=cred)

        search_fn = next(fn for fn in fns if fn.__name__ == "zoho_crm_search")
        with patch("aden_tools.tools.zoho_crm_tool.zoho_crm_tool.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [], "info": {"page": 1, "per_page": 2}}),
            )
            result = search_fn(module="Leads", word="Zoho")

        assert result["success"] is True
        called_url = mock_get.call_args.args[0]
        assert called_url.startswith("https://www.zohoapis.in/crm/v8/")


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_zoho_crm_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "zoho_crm" in CREDENTIAL_SPECS

    def test_zoho_crm_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["zoho_crm"]
        assert spec.env_var == "ZOHO_REFRESH_TOKEN"

    def test_zoho_crm_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["zoho_crm"]
        assert "zoho_crm_search" in spec.tools
        assert "zoho_crm_get_record" in spec.tools
        assert "zoho_crm_create_record" in spec.tools
        assert "zoho_crm_update_record" in spec.tools
        assert "zoho_crm_add_note" in spec.tools
        assert len(spec.tools) == 5
