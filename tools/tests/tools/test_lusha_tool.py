"""
Tests for Lusha tool integration.

Covers:
- _LushaClient request and error handling
- Credential retrieval behavior
- Input validation for required parameters
- MCP registration for all Lusha tools
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from aden_tools.tools.lusha_tool.lusha_tool import (
    LUSHA_API_BASE,
    _LushaClient,
    register_tools,
)


class TestLushaClient:
    def setup_method(self):
        self.client = _LushaClient("test-lusha-key")

    def test_headers(self):
        headers = self.client._headers
        assert headers["api_key"] == "test-lusha-key"
        assert headers["Accept"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {"ok": True}
        assert self.client._handle_response(response) == {"ok": True}

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_enrich_person_uses_v2_person(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": {"email": "a@b.com"}}
        mock_request.return_value = mock_response

        result = self.client.enrich_person(email="a@b.com")

        assert result["person"]["email"] == "a@b.com"
        mock_request.assert_called_once_with(
            "GET",
            f"{LUSHA_API_BASE}/v2/person",
            headers=self.client._headers,
            params={"email": "a@b.com"},
            json=None,
            timeout=30.0,
        )

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_enrich_person_uses_linkedin_url_param(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": {"id": "p1"}}
        mock_request.return_value = mock_response

        self.client.enrich_person(linkedin_url="https://www.linkedin.com/in/example/")

        mock_request.assert_called_once_with(
            "GET",
            f"{LUSHA_API_BASE}/v2/person",
            headers=self.client._headers,
            params={"linkedinUrl": "https://www.linkedin.com/in/example/"},
            json=None,
            timeout=30.0,
        )

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_enrich_company_uses_v2_company(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"company": {"domain": "openai.com"}}
        mock_request.return_value = mock_response

        result = self.client.enrich_company(domain="openai.com")

        assert result["company"]["domain"] == "openai.com"
        mock_request.assert_called_once_with(
            "GET",
            f"{LUSHA_API_BASE}/v2/company",
            headers=self.client._headers,
            params={"domain": "openai.com"},
            json=None,
            timeout=30.0,
        )

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_search_people_structured_filters(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"contacts": [{"id": "c1"}]}
        mock_request.return_value = mock_response

        result = self.client.search_people(
            job_titles=["VP Sales", "Director Sales"],
            seniority=[8],
            departments=["Sales"],
            locations=[{"country": "United States", "city": "New York"}],
            company_names=["Acme"],
            industry_ids=[4, 5],
            limit=25,
        )

        assert result["contacts"][0]["id"] == "c1"
        body = mock_request.call_args.kwargs["json"]
        assert body["pages"] == {"size": 25, "page": 0}
        assert body["filters"]["contacts"]["include"]["jobTitles"] == [
            "VP Sales",
            "Director Sales",
        ]
        assert body["filters"]["contacts"]["include"]["seniority"] == [8]
        assert body["filters"]["contacts"]["include"]["departments"] == ["Sales"]
        assert body["filters"]["contacts"]["include"]["locations"] == [
            {"country": "United States", "city": "New York"}
        ]
        assert body["filters"]["companies"]["include"]["names"] == ["Acme"]
        assert body["filters"]["companies"]["include"]["mainIndustriesIds"] == [4, 5]
        assert "searchText" not in body["filters"]["contacts"]["include"]
        assert mock_request.call_args.args[1] == f"{LUSHA_API_BASE}/prospecting/contact/search"

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_search_people_with_search_text(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"contacts": []}
        mock_request.return_value = mock_response

        self.client.search_people(search_text="Amit", departments=["Engineering & Technical"])

        body = mock_request.call_args.kwargs["json"]
        assert body["filters"]["contacts"]["include"]["searchText"] == "Amit"
        assert body["filters"]["contacts"]["include"]["departments"] == ["Engineering & Technical"]

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_search_people_limit_capped_at_50(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"contacts": []}
        mock_request.return_value = mock_response

        self.client.search_people(job_titles=["CTO"], limit=200)

        body = mock_request.call_args.kwargs["json"]
        assert body["pages"]["size"] == 50

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_search_companies_body(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"companies": [{"id": "co1"}]}
        mock_request.return_value = mock_response

        result = self.client.search_companies(
            industry_ids=[4, 5],
            employee_size="51-200",
            locations=[{"country": "United States"}],
            limit=30,
        )

        assert result["companies"][0]["id"] == "co1"
        body = mock_request.call_args.kwargs["json"]
        assert body["pages"] == {"size": 30, "page": 0}
        assert body["filters"]["companies"]["include"]["mainIndustriesIds"] == [4, 5]
        assert body["filters"]["companies"]["include"]["sizes"] == [{"min": 51, "max": 200}]
        assert body["filters"]["companies"]["include"]["locations"] == [
            {"country": "United States"}
        ]
        assert mock_request.call_args.args[1] == f"{LUSHA_API_BASE}/prospecting/company/search"

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_search_companies_no_industry(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"companies": []}
        mock_request.return_value = mock_response

        self.client.search_companies(
            employee_size="51-200",
            locations=[{"country": "United States"}],
        )

        body = mock_request.call_args.kwargs["json"]
        assert "mainIndustriesIds" not in body["filters"]["companies"]["include"]

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_get_signals_contact(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"signals": [{"id": "c1"}]}
        mock_request.return_value = mock_response

        result = self.client.get_signals(entity_type="contact", ids=[123])

        assert result["signals"][0]["id"] == "c1"
        assert mock_request.call_args.args[1] == f"{LUSHA_API_BASE}/api/signals/contacts"
        assert mock_request.call_args.kwargs["json"] == {
            "contactIds": [123],
            "signals": ["allSignals"],
        }

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_get_account_usage(self, mock_request):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"remaining": 100}
        mock_request.return_value = mock_response

        result = self.client.get_account_usage()
        assert result["remaining"] == 100
        assert mock_request.call_args.args[1] == f"{LUSHA_API_BASE}/account/usage"

    def test_get_signals_invalid_entity_type(self):
        result = self.client.get_signals(entity_type="invalid", ids=[123])
        assert result == {"error": "entity_type must be one of: contact, company"}

    def test_get_signals_empty_ids(self):
        result = self.client.get_signals(entity_type="contact", ids=[])
        assert result == {"error": "ids must contain at least one value"}


class TestToolFunctions:
    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_missing_credentials_returns_help(self, mock_request, monkeypatch):
        from fastmcp import FastMCP

        monkeypatch.delenv("LUSHA_API_KEY", raising=False)
        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        fn = mcp._tool_manager._tools["lusha_enrich_person"].fn
        result = fn(email="a@b.com")

        assert "error" in result
        assert "help" in result
        mock_request.assert_not_called()

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_enrich_person_validation(self, mock_request, monkeypatch):
        from fastmcp import FastMCP

        monkeypatch.setenv("LUSHA_API_KEY", "test-key")
        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        fn = mcp._tool_manager._tools["lusha_enrich_person"].fn
        result = fn()

        assert "error" in result
        assert "email" in result["error"]
        mock_request.assert_not_called()

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_get_signals_validation(self, mock_request, monkeypatch):
        from fastmcp import FastMCP

        monkeypatch.setenv("LUSHA_API_KEY", "test-key")
        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        fn = mcp._tool_manager._tools["lusha_get_signals"].fn
        result = fn(entity_type="contact", ids=[])

        assert "error" in result
        assert "ids" in result["error"]
        mock_request.assert_not_called()

    @patch("aden_tools.tools.lusha_tool.lusha_tool.httpx.request")
    def test_non_string_credential_returns_error(self, mock_request):
        """Non-string credential returns error dict instead of raising."""
        from fastmcp import FastMCP

        creds = MagicMock()
        creds.get.return_value = 12345  # non-string

        mcp = FastMCP("test")
        register_tools(mcp, credentials=creds)

        fn = mcp._tool_manager._tools["lusha_enrich_person"].fn
        result = fn(email="a@b.com")

        assert "error" in result
        assert "credentials" in result["error"].lower()
        mock_request.assert_not_called()

    def test_registers_all_tools(self):
        from fastmcp import FastMCP

        mcp = FastMCP("test-register")
        register_tools(mcp, credentials=None)

        registered = set(mcp._tool_manager._tools.keys())
        assert "lusha_enrich_person" in registered
        assert "lusha_enrich_company" in registered
        assert "lusha_search_people" in registered
        assert "lusha_search_companies" in registered
        assert "lusha_get_signals" in registered
        assert "lusha_get_account_usage" in registered
