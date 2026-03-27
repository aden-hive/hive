"""
Tests for the NinjaPear enrichment tool.

Covers:
- _NinjaPearClient: headers, _handle_response (all status codes), each API method
- Tool registration: all 7 tools, no-credentials error, env var, credential manager
- ninjapear_get_person_profile: valid input combos, insufficient-input guard
- ninjapear_get_company_details: happy path, optional flags, missing website
- ninjapear_get_company_funding: happy path, missing website
- ninjapear_get_company_updates: happy path, missing website
- ninjapear_get_company_customers: happy path, page_size validation
- ninjapear_get_company_competitors: happy path, missing website
- ninjapear_get_credit_balance: happy path, no-credentials error
- Timeout / network error handling (all tools)
- CredentialSpec: env_var, tools list
- @pytest.mark.live: real API smoke tests (skipped unless NINJAPEAR_API_KEY is set)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.ninjapear_tool.ninjapear_tool import (
    NINJAPEAR_API_BASE,
    _NinjaPearClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOOL_NAMES = [
    "ninjapear_get_person_profile",
    "ninjapear_get_company_details",
    "ninjapear_get_company_funding",
    "ninjapear_get_company_updates",
    "ninjapear_get_company_customers",
    "ninjapear_get_company_competitors",
    "ninjapear_get_credit_balance",
]


def _make_response(status_code: int, body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body or {}
    r.text = str(body or {})
    return r


def _register(credentials=None) -> tuple[MagicMock, list, dict]:
    """Register tools into a mock MCP and return (mcp, fns_list, fn_by_name)."""
    mcp = MagicMock()
    fns: list = []
    mcp.tool.return_value = lambda fn: fns.append(fn) or fn
    register_tools(mcp, credentials=credentials)
    by_name = {fn.__name__: fn for fn in fns}
    return mcp, fns, by_name


# ---------------------------------------------------------------------------
# _NinjaPearClient
# ---------------------------------------------------------------------------


class TestNinjaPearClient:
    def setup_method(self):
        self.client = _NinjaPearClient("test-key")

    # --- headers ---

    def test_headers_authorization(self):
        assert self.client._headers["Authorization"] == "Bearer test-key"

    def test_headers_accept(self):
        assert self.client._headers["Accept"] == "application/json"

    # --- _handle_response ---

    def test_handle_response_200(self):
        r = _make_response(200, {"name": "Stripe"})
        assert self.client._handle_response(r) == {"name": "Stripe"}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid"),
            (403, "credits"),
            (404, "Not found"),
            (410, "deprecated"),
            (429, "rate limit"),
            (503, "retry"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        r = _make_response(status_code)
        result = self.client._handle_response(r)
        assert "error" in result
        assert expected_substring.lower() in result["error"].lower()

    def test_handle_response_generic_5xx(self):
        r = _make_response(500, {"detail": "boom"})
        result = self.client._handle_response(r)
        assert "error" in result
        assert "500" in result["error"]

    def test_handle_response_invalid_json(self):
        r = MagicMock()
        r.status_code = 200
        r.json.side_effect = ValueError("not json")
        r.text = "not-json-body"
        result = self.client._handle_response(r)
        assert "error" in result

    # --- get_person_profile ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_person_profile_by_email(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "Jane Doe"})
        result = self.client.get_person_profile(work_email="jane@stripe.com")
        assert result["full_name"] == "Jane Doe"
        params = mock_get.call_args.kwargs["params"]
        assert params["work_email"] == "jane@stripe.com"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_person_profile_by_name_employer(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "John Smith"})
        self.client.get_person_profile(
            first_name="John", last_name="Smith", employer_website="stripe.com"
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["first_name"] == "John"
        assert params["last_name"] == "Smith"
        assert params["employer_website"] == "stripe.com"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_person_profile_by_role_employer(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "Alice"})
        self.client.get_person_profile(employer_website="stripe.com", role="CTO")
        params = mock_get.call_args.kwargs["params"]
        assert params["role"] == "CTO"
        assert params["employer_website"] == "stripe.com"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_person_profile_empty_params_omitted(self, mock_get):
        """Empty string params must not be sent to the API."""
        mock_get.return_value = _make_response(200, {})
        self.client.get_person_profile(slug="janesmith")
        params = mock_get.call_args.kwargs["params"]
        assert "work_email" not in params
        assert "first_name" not in params
        assert params["slug"] == "janesmith"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_person_profile_timeout_100s(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_person_profile(slug="x")
        assert mock_get.call_args.kwargs["timeout"] == 100.0

    # --- get_company_details ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_details_basic(self, mock_get):
        mock_get.return_value = _make_response(200, {"name": "Stripe"})
        result = self.client.get_company_details("stripe.com")
        assert result["name"] == "Stripe"
        url = mock_get.call_args.args[0]
        assert url == f"{NINJAPEAR_API_BASE}/api/v1/company/details"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_details_employee_count_flag(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_details("stripe.com", include_employee_count=True)
        params = mock_get.call_args.kwargs["params"]
        assert params["include_employee_count"] == "true"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_details_follower_count_flag(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_details("stripe.com", include_follower_count=True)
        params = mock_get.call_args.kwargs["params"]
        assert params["follower_count"] == "include"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_details_no_optional_flags(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_details("stripe.com")
        params = mock_get.call_args.kwargs["params"]
        assert "include_employee_count" not in params
        assert "follower_count" not in params

    # --- get_company_funding ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_funding(self, mock_get):
        body = {"total_funds_raised_usd": 2000000000, "funding_rounds": []}
        mock_get.return_value = _make_response(200, body)
        result = self.client.get_company_funding("stripe.com")
        assert result["total_funds_raised_usd"] == 2000000000
        url = mock_get.call_args.args[0]
        assert url == f"{NINJAPEAR_API_BASE}/api/v1/company/funding"

    # --- get_company_updates ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_updates(self, mock_get):
        body = {"updates": [{"title": "We are hiring"}], "blogs": []}
        mock_get.return_value = _make_response(200, body)
        result = self.client.get_company_updates("stripe.com")
        assert result["updates"][0]["title"] == "We are hiring"
        url = mock_get.call_args.args[0]
        assert url == f"{NINJAPEAR_API_BASE}/api/v1/company/updates"

    # --- get_company_customers ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_customers_default_params(self, mock_get):
        mock_get.return_value = _make_response(200, {"customers": []})
        self.client.get_company_customers("stripe.com")
        params = mock_get.call_args.kwargs["params"]
        assert params["website"] == "stripe.com"
        # Client default is 200; the tool function default (50) is a separate layer
        assert params["page_size"] == 200
        # quality_filter=True means param is not sent (default)
        assert "quality_filter" not in params

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_customers_quality_filter_false(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_customers("stripe.com", quality_filter=False)
        params = mock_get.call_args.kwargs["params"]
        assert params["quality_filter"] == "false"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_customers_page_size_forwarded(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_customers("stripe.com", page_size=50)
        params = mock_get.call_args.kwargs["params"]
        assert params["page_size"] == 50

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_customers_cursor(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self.client.get_company_customers("stripe.com", cursor="abc123")
        params = mock_get.call_args.kwargs["params"]
        assert params["cursor"] == "abc123"

    # --- get_company_competitors ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_company_competitors(self, mock_get):
        body = {
            "competitors": [{"website": "braintree.com", "competition_reason": "product_overlap"}]
        }
        mock_get.return_value = _make_response(200, body)
        result = self.client.get_company_competitors("stripe.com")
        assert result["competitors"][0]["website"] == "braintree.com"
        url = mock_get.call_args.args[0]
        assert url == f"{NINJAPEAR_API_BASE}/api/v1/competitor/listing"

    # --- get_credit_balance ---

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_credit_balance(self, mock_get):
        mock_get.return_value = _make_response(200, {"credit_balance": 9500})
        result = self.client.get_credit_balance()
        assert result["credit_balance"] == 9500
        url = mock_get.call_args.args[0]
        assert url == f"{NINJAPEAR_API_BASE}/api/v1/meta/credit-balance"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_get_credit_balance_timeout_30s(self, mock_get):
        mock_get.return_value = _make_response(200, {"credit_balance": 0})
        self.client.get_credit_balance()
        assert mock_get.call_args.kwargs["timeout"] == 30.0


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_tools_registered(self):
        _, _, by_name = _register()
        for name in TOOL_NAMES:
            assert name in by_name, f"Tool '{name}' was not registered"

    def test_tool_count(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == len(TOOL_NAMES)

    def test_no_credentials_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            _, _, by_name = _register(credentials=None)
            result = by_name["ninjapear_get_credit_balance"]()
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_env_var(self):
        _, _, by_name = _register(credentials=None)
        with (
            patch.dict("os.environ", {"NINJAPEAR_API_KEY": "env-key"}),
            patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value = _make_response(200, {"credit_balance": 10})
            result = by_name["ninjapear_get_credit_balance"]()
        assert result["credit_balance"] == 10
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer env-key"

    def test_credentials_from_credential_manager(self):
        cred = MagicMock()
        cred.get.return_value = "manager-key"
        _, _, by_name = _register(credentials=cred)
        with patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get") as mock_get:
            mock_get.return_value = _make_response(200, {"credit_balance": 42})
            result = by_name["ninjapear_get_credit_balance"]()
        cred.get.assert_called_with("ninjapear")
        assert result["credit_balance"] == 42


# ---------------------------------------------------------------------------
# ninjapear_get_person_profile
# ---------------------------------------------------------------------------


class TestPersonProfileTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_person_profile"]

    def test_no_input_returns_error(self):
        result = self._fn()()
        assert "error" in result
        assert "Insufficient input" in result["error"]

    def test_partial_input_name_without_employer_returns_error(self):
        # first_name alone is not a valid combo
        result = self._fn()(first_name="Jane")
        assert "error" in result

    def test_partial_input_role_without_employer_returns_error(self):
        result = self._fn()(role="CTO")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_valid_work_email(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "Jane Doe"})
        result = self._fn()(work_email="jane@stripe.com")
        assert result["full_name"] == "Jane Doe"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_valid_name_plus_employer(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "John"})
        result = self._fn()(first_name="John", employer_website="stripe.com")
        assert "full_name" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_valid_role_plus_employer(self, mock_get):
        mock_get.return_value = _make_response(200, {"full_name": "Alice"})
        result = self._fn()(role="CTO", employer_website="stripe.com")
        assert "full_name" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_valid_slug(self, mock_get):
        mock_get.return_value = _make_response(200, {"slug": "janesmith"})
        result = self._fn()(slug="janesmith")
        assert "slug" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_valid_profile_id(self, mock_get):
        mock_get.return_value = _make_response(200, {"id": "abc12345"})
        result = self._fn()(profile_id="abc12345")
        assert "id" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_timeout_returns_error(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn()(work_email="jane@stripe.com")
        assert "error" in result
        assert "timed out" in result["error"].lower() or "100s" in result["error"]

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_network_error_returns_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn()(work_email="jane@stripe.com")
        assert "error" in result
        assert "Network error" in result["error"]


# ---------------------------------------------------------------------------
# ninjapear_get_company_details
# ---------------------------------------------------------------------------


class TestCompanyDetailsTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_company_details"]

    def test_missing_website_returns_error(self):
        result = self._fn()(website="")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        mock_get.return_value = _make_response(200, {"name": "Stripe", "founded_year": 2010})
        result = self._fn()(website="stripe.com")
        assert result["name"] == "Stripe"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_with_employee_count_flag(self, mock_get):
        mock_get.return_value = _make_response(200, {"employee_count": 7000})
        result = self._fn()(website="stripe.com", include_employee_count=True)
        assert result["employee_count"] == 7000
        params = mock_get.call_args.kwargs["params"]
        assert params["include_employee_count"] == "true"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_timeout_returns_error(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn()(website="stripe.com")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_network_error_returns_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn()(website="stripe.com")
        assert "error" in result


# ---------------------------------------------------------------------------
# ninjapear_get_company_funding
# ---------------------------------------------------------------------------


class TestCompanyFundingTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_company_funding"]

    def test_missing_website_returns_error(self):
        result = self._fn()(website="")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        body = {
            "total_funds_raised_usd": 2000000000,
            "funding_rounds": [{"round_type": "SERIES_A", "amount_usd": 5000000, "investors": []}],
        }
        mock_get.return_value = _make_response(200, body)
        result = self._fn()(website="stripe.com")
        assert result["total_funds_raised_usd"] == 2000000000
        assert len(result["funding_rounds"]) == 1


# ---------------------------------------------------------------------------
# ninjapear_get_company_updates
# ---------------------------------------------------------------------------


class TestCompanyUpdatesTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_company_updates"]

    def test_missing_website_returns_error(self):
        result = self._fn()(website="")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        body = {
            "updates": [
                {"title": "We're hiring 500 engineers", "source": "blog", "timestamp": "2024-01-15"}
            ],
            "blogs": ["https://stripe.com/blog"],
        }
        mock_get.return_value = _make_response(200, body)
        result = self._fn()(website="stripe.com")
        assert len(result["updates"]) == 1
        assert "hiring" in result["updates"][0]["title"]


# ---------------------------------------------------------------------------
# ninjapear_get_company_customers
# ---------------------------------------------------------------------------


class TestCompanyCustomersTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_company_customers"]

    def test_missing_website_returns_error(self):
        result = self._fn()(website="")
        assert "error" in result

    def test_page_size_too_large_returns_error(self):
        result = self._fn()(website="stripe.com", page_size=999)
        assert "error" in result

    def test_page_size_zero_returns_error(self):
        result = self._fn()(website="stripe.com", page_size=0)
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        body = {
            "customers": [{"name": "Amazon", "website": "amazon.com"}],
            "investors": [],
            "partner_platforms": [],
            "next_page": None,
        }
        mock_get.return_value = _make_response(200, body)
        result = self._fn()(website="stripe.com")
        assert result["customers"][0]["name"] == "Amazon"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_pagination_cursor_forwarded(self, mock_get):
        mock_get.return_value = _make_response(200, {"customers": [], "next_page": None})
        self._fn()(website="stripe.com", cursor="next-page-token")
        params = mock_get.call_args.kwargs["params"]
        assert params["cursor"] == "next-page-token"

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_quality_filter_false_forwarded(self, mock_get):
        mock_get.return_value = _make_response(200, {})
        self._fn()(website="stripe.com", quality_filter=False)
        params = mock_get.call_args.kwargs["params"]
        assert params["quality_filter"] == "false"


# ---------------------------------------------------------------------------
# ninjapear_get_company_competitors
# ---------------------------------------------------------------------------


class TestCompanyCompetitorsTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_company_competitors"]

    def test_missing_website_returns_error(self):
        result = self._fn()(website="")
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        body = {
            "competitors": [
                {"website": "braintree.com", "competition_reason": "product_overlap"},
                {"website": "adyen.com", "competition_reason": "organic_keyword_overlap"},
            ]
        }
        mock_get.return_value = _make_response(200, body)
        result = self._fn()(website="stripe.com")
        assert len(result["competitors"]) == 2
        assert result["competitors"][0]["competition_reason"] == "product_overlap"


# ---------------------------------------------------------------------------
# ninjapear_get_credit_balance
# ---------------------------------------------------------------------------


class TestCreditBalanceTool:
    def setup_method(self):
        cred = MagicMock()
        cred.get.return_value = "tok"
        _, _, self.fns = _register(credentials=cred)

    def _fn(self):
        return self.fns["ninjapear_get_credit_balance"]

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_happy_path(self, mock_get):
        mock_get.return_value = _make_response(200, {"credit_balance": 9500})
        result = self._fn()()
        assert result["credit_balance"] == 9500

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_timeout_returns_error(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn()()
        assert "error" in result

    @patch("aden_tools.tools.ninjapear_tool.ninjapear_tool.httpx.get")
    def test_network_error_returns_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("conn refused")
        result = self._fn()()
        assert "error" in result
        assert "Network error" in result["error"]

    def test_no_credentials_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            _, _, fns = _register(credentials=None)
            result = fns["ninjapear_get_credit_balance"]()
        assert "error" in result
        assert "not configured" in result["error"]


# ---------------------------------------------------------------------------
# CredentialSpec
# ---------------------------------------------------------------------------


class TestCredentialSpec:
    def test_spec_exists(self):
        from aden_tools.credentials import NINJAPEAR_CREDENTIALS

        assert "ninjapear" in NINJAPEAR_CREDENTIALS

    def test_env_var(self):
        from aden_tools.credentials import NINJAPEAR_CREDENTIALS

        assert NINJAPEAR_CREDENTIALS["ninjapear"].env_var == "NINJAPEAR_API_KEY"

    def test_tools_list_complete(self):
        from aden_tools.credentials import NINJAPEAR_CREDENTIALS

        spec_tools = NINJAPEAR_CREDENTIALS["ninjapear"].tools
        for name in TOOL_NAMES:
            assert name in spec_tools, f"Tool '{name}' missing from CredentialSpec.tools"

    def test_health_check_endpoint(self):
        from aden_tools.credentials import NINJAPEAR_CREDENTIALS

        spec = NINJAPEAR_CREDENTIALS["ninjapear"]
        assert "credit-balance" in spec.health_check_endpoint

    def test_in_global_credential_specs(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "ninjapear" in CREDENTIAL_SPECS


# ---------------------------------------------------------------------------
# Live tests — skipped unless NINJAPEAR_API_KEY is set in environment
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLive:
    """
    Real API calls against NinjaPear. Excluded from CI by default.

    To run:
        export NINJAPEAR_API_KEY=your-key
        cd tools
        uv run pytest src/aden_tools/tools/ninjapear_tool/tests/ -m live -v
    """

    @pytest.fixture(autouse=True)
    def require_api_key(self):
        if not os.environ.get("NINJAPEAR_API_KEY"):
            pytest.skip("NINJAPEAR_API_KEY not set")

    def test_live_credit_balance(self):
        """Smoke test: free endpoint, 0 credits consumed."""
        _, _, fns = _register(credentials=None)
        result = fns["ninjapear_get_credit_balance"]()
        assert "credit_balance" in result, f"Unexpected response: {result}"
        assert isinstance(result["credit_balance"], int)

    def test_live_company_details_stripe(self):
        """Fetch Stripe company details. Costs 2 credits."""
        _, _, fns = _register(credentials=None)
        result = fns["ninjapear_get_company_details"](website="stripe.com")
        assert "error" not in result, f"API error: {result}"
        assert result.get("name") is not None

    def test_live_person_profile_by_role(self):
        """Look up CTO at stripe.com. Costs 3 credits."""
        _, _, fns = _register(credentials=None)
        result = fns["ninjapear_get_person_profile"](role="CTO", employer_website="stripe.com")
        # 404 is acceptable (person may not be indexed), anything else is a bug
        if "error" in result:
            assert "Not found" in result["error"], f"Unexpected error: {result}"
        else:
            assert "full_name" in result or "id" in result
