"""
Tests for Apollo.io data enrichment tool.

Covers:
- _ApolloClient methods (enrich_person, enrich_company, search_people, search_companies)
- Error handling (401, 403, 404, 422, 429, 500, timeout)
- 429 retry with Retry-After header via _request
- Credential retrieval (CredentialStoreAdapter vs env var)
- All MCP tool functions (async)
- "Not found" graceful handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aden_tools.tools.apollo_tool.apollo_tool import (
    APOLLO_API_BASE,
    _ApolloClient,
    register_tools,
)


def _mock_response(status_code: int, json_data: dict, headers: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.text = str(json_data)
    r.headers = headers or {}
    return r


def _mock_async_client(response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient context manager."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# --- _ApolloClient._handle_response tests (sync) ---


class TestHandleResponse:
    def setup_method(self):
        self.client = _ApolloClient("test-api-key")

    def test_success(self):
        r = _mock_response(200, {"person": {"id": "123"}})
        assert self.client._handle_response(r) == {"person": {"id": "123"}}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid Apollo API key"),
            (403, "Insufficient credits"),
            (404, "not found"),
            (422, "Invalid parameters"),
            (429, "rate limit"),
        ],
    )
    def test_error_codes(self, status_code, expected_substring):
        r = _mock_response(status_code, {"error": "Test error"})
        result = self.client._handle_response(r)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_429_includes_retry_after(self):
        r = _mock_response(429, {}, headers={"Retry-After": "42"})
        result = self.client._handle_response(r)
        assert result["retry_after_seconds"] == 42

    def test_429_defaults_retry_after_60(self):
        r = _mock_response(429, {}, headers={})
        result = self.client._handle_response(r)
        assert result["retry_after_seconds"] == 60

    def test_generic_5xx(self):
        r = _mock_response(500, {"error": "Internal Server Error"})
        result = self.client._handle_response(r)
        assert "500" in result["error"]


# --- _ApolloClient._request retry tests ---


class TestRequestRetry:
    def setup_method(self):
        self.client = _ApolloClient("test-api-key")

    async def test_retries_on_429_then_succeeds(self):
        resp_429 = _mock_response(429, {}, headers={"Retry-After": "0"})
        resp_200 = _mock_response(200, {"ok": True})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[resp_429, resp_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                response = await self.client._request("post", "http://test", timeout=5.0)

        assert mock_client.post.call_count == 2
        mock_sleep.assert_called_once_with(0)
        assert response.status_code == 200

    async def test_returns_429_after_max_retries(self):
        resp_429 = _mock_response(429, {}, headers={"Retry-After": "0"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp_429)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                response = await self.client._request("post", "http://test", max_retries=2, timeout=5.0)

        assert mock_client.post.call_count == 3  # 1 initial + 2 retries
        assert response.status_code == 429


# --- _ApolloClient async method tests ---


class TestApolloClientMethods:
    def setup_method(self):
        self.client = _ApolloClient("test-api-key")

    async def test_enrich_person_by_email(self):
        r = _mock_response(200, {
            "person": {
                "id": "p123", "first_name": "John", "last_name": "Doe",
                "name": "John Doe", "title": "VP Sales", "email": "john@acme.com",
                "email_status": "verified", "phone_numbers": [],
                "linkedin_url": None, "twitter_url": None,
                "city": "SF", "state": "CA", "country": "US",
                "organization": {
                    "id": "o1", "name": "Acme", "primary_domain": "acme.com",
                    "industry": "Tech", "estimated_num_employees": 250,
                },
            }
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.enrich_person(email="john@acme.com")

        assert result["match_found"] is True
        assert result["person"]["first_name"] == "John"
        assert result["person"]["organization"]["name"] == "Acme"

    async def test_enrich_person_not_found(self):
        r = _mock_response(200, {"person": None})
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.enrich_person(email="nobody@nowhere.xyz")
        assert result["match_found"] is False

    async def test_enrich_company(self):
        r = _mock_response(200, {
            "organization": {
                "id": "o1", "name": "OpenAI", "primary_domain": "openai.com",
                "website_url": None, "linkedin_url": None, "twitter_url": None,
                "facebook_url": None, "industry": "AI", "keywords": [],
                "estimated_num_employees": 1500, "employee_count_range": "1001-5000",
                "annual_revenue": None, "annual_revenue_printed": None,
                "total_funding": None, "total_funding_printed": None,
                "latest_funding_round_date": None, "latest_funding_stage": None,
                "founded_year": 2015, "phone": None, "city": "SF", "state": "CA",
                "country": "US", "street_address": None, "technologies": [],
                "short_description": "AI company",
            }
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.enrich_company("openai.com")

        assert result["match_found"] is True
        assert result["organization"]["name"] == "OpenAI"

    async def test_enrich_company_not_found(self):
        r = _mock_response(200, {"organization": None})
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.enrich_company("notreal.xyz")
        assert result["match_found"] is False

    async def test_search_people(self):
        r = _mock_response(200, {
            "pagination": {"total_entries": 150, "page": 1, "per_page": 10},
            "people": [
                {"id": "p1", "first_name": "Alice", "last_name": "J", "name": "Alice J",
                 "title": "VP Sales", "email": "alice@co.com", "email_status": "verified",
                 "linkedin_url": None, "city": "NY", "state": "NY", "country": "US",
                 "seniority": "vp", "organization": {"id": "o1", "name": "Co", "primary_domain": "co.com"}},
            ],
        })
        mock_client = _mock_async_client(r)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.client.search_people(
                titles=["VP Sales"], seniorities=["vp"], limit=10
            )

        assert result["total"] == 150
        assert len(result["results"]) == 1
        call_json = mock_client.post.call_args.kwargs["json"]
        assert call_json["person_titles"] == ["VP Sales"]
        assert call_json["per_page"] == 10

    async def test_search_people_limit_capped_at_100(self):
        r = _mock_response(200, {"pagination": {}, "people": []})
        mock_client = _mock_async_client(r)
        with patch("httpx.AsyncClient", return_value=mock_client):
            await self.client.search_people(limit=200)
        call_json = mock_client.post.call_args.kwargs["json"]
        assert call_json["per_page"] == 100

    async def test_search_companies(self):
        r = _mock_response(200, {
            "pagination": {"total_entries": 50, "page": 1, "per_page": 10},
            "organizations": [
                {"id": "o1", "name": "Tech Corp", "primary_domain": "tc.io",
                 "website_url": None, "linkedin_url": None, "industry": "Technology",
                 "estimated_num_employees": 75, "employee_count_range": "51-200",
                 "annual_revenue_printed": None, "city": "Austin", "state": "TX",
                 "country": "US", "short_description": "A tech co"},
            ],
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.search_companies(industries=["technology"], limit=10)

        assert result["total"] == 50
        assert result["results"][0]["name"] == "Tech Corp"

    async def test_bulk_enrich_people(self):
        r = _mock_response(200, {
            "matches": [
                {"id": "p1", "name": "John", "title": "CEO", "email": "j@co.com",
                 "email_status": "verified", "linkedin_url": None, "organization": {"name": "Co"}},
            ]
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.bulk_enrich_people([{"email": "j@co.com"}])
        assert result["count"] == 1
        assert result["results"][0]["match_found"] is True

    async def test_list_email_accounts(self):
        r = _mock_response(200, {
            "email_accounts": [
                {"id": "e1", "email": "test@co.com", "type": "smtp", "active": True,
                 "default": True, "last_synced_at": None, "sending_daily_limit": 200,
                 "emails_sent_today": 10}
            ]
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.list_email_accounts()
        assert result["count"] == 1

    async def test_get_person_activities(self):
        r = _mock_response(200, {
            "activities": [
                {"id": "a1", "type": "email", "subject": "Hello", "body": "Hi there",
                 "created_at": "2024-01-01", "completed_at": None,
                 "status": "sent", "priority": "normal"}
            ]
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self.client.get_person_activities("person-123")
        assert result["count"] == 1
        assert result["contact_id"] == "person-123"


# --- MCP tool registration tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 7

    async def test_no_credentials_returns_error(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        enrich_fn = next(fn for fn in fns if fn.__name__ == "apollo_enrich_person")
        result = await enrich_fn(email="test@test.com")
        assert "error" in result
        assert "not configured" in result["error"]

    async def test_credentials_from_credential_manager(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn

        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(mcp, credentials=cred)

        enrich_fn = next(fn for fn in fns if fn.__name__ == "apollo_enrich_company")
        r = _mock_response(200, {"organization": {"id": "1", "name": "Test", "primary_domain": "t.com",
                                                   "website_url": None, "linkedin_url": None, "twitter_url": None,
                                                   "facebook_url": None, "industry": None, "keywords": [],
                                                   "estimated_num_employees": None, "employee_count_range": None,
                                                   "annual_revenue": None, "annual_revenue_printed": None,
                                                   "total_funding": None, "total_funding_printed": None,
                                                   "latest_funding_round_date": None, "latest_funding_stage": None,
                                                   "founded_year": None, "phone": None, "city": None, "state": None,
                                                   "country": None, "street_address": None, "technologies": [],
                                                   "short_description": None}})
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await enrich_fn(domain="test.com")

        cred.get.assert_called_with("apollo")
        assert result["match_found"] is True

    async def test_credentials_from_env_var(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        register_tools(mcp, credentials=None)

        enrich_fn = next(fn for fn in fns if fn.__name__ == "apollo_enrich_company")
        r = _mock_response(200, {"organization": None})

        with patch.dict("os.environ", {"APOLLO_API_KEY": "env-api-key"}):
            with patch("httpx.AsyncClient", return_value=_mock_async_client(r)) as MockClient:
                await enrich_fn(domain="test.com")

        # Verify client was called (key is in headers of the _ApolloClient instance)
        assert MockClient.called


# --- MCP tool function validation tests ---


class TestEnrichPersonValidation:
    def setup_method(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(mcp, credentials=cred)
        self._fns = fns

    def _fn(self, name):
        return next(f for f in self._fns if f.__name__ == name)

    async def test_enrich_person_requires_email_or_linkedin(self):
        result = await self._fn("apollo_enrich_person")()
        assert "error" in result
        assert "Invalid search criteria" in result["error"]

    async def test_enrich_person_timeout(self):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            result = await self._fn("apollo_enrich_person")(email="test@test.com")
        assert "timed out" in result["error"]

    async def test_enrich_person_network_error(self):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.RequestError("connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            result = await self._fn("apollo_enrich_person")(email="test@test.com")
        assert "Network error" in result["error"]

    async def test_bulk_enrich_people_invalid_json(self):
        result = await self._fn("apollo_bulk_enrich_people")(details_json="not-json")
        assert "error" in result
        assert "valid JSON" in result["error"]

    async def test_bulk_enrich_people_too_many(self):
        import json
        details = [{"email": f"p{i}@co.com"} for i in range(11)]
        result = await self._fn("apollo_bulk_enrich_people")(details_json=json.dumps(details))
        assert "maximum 10" in result["error"]


class TestEnrichCompanyTool:
    def setup_method(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(mcp, credentials=cred)
        self._fns = fns

    def _fn(self, name):
        return next(f for f in self._fns if f.__name__ == name)

    async def test_enrich_company_success(self):
        r = _mock_response(200, {
            "organization": {
                "id": "o1", "name": "Acme Inc", "primary_domain": "acme.com",
                "industry": "Technology", "estimated_num_employees": 500,
                "website_url": None, "linkedin_url": None, "twitter_url": None,
                "facebook_url": None, "keywords": [], "employee_count_range": None,
                "annual_revenue": None, "annual_revenue_printed": None,
                "total_funding": None, "total_funding_printed": None,
                "latest_funding_round_date": None, "latest_funding_stage": None,
                "founded_year": None, "phone": None, "city": None, "state": None,
                "country": None, "street_address": None, "technologies": [],
                "short_description": None,
            }
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self._fn("apollo_enrich_company")(domain="acme.com")
        assert result["match_found"] is True
        assert result["organization"]["name"] == "Acme Inc"

    async def test_enrich_company_not_found(self):
        r = _mock_response(200, {"organization": None})
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self._fn("apollo_enrich_company")(domain="notreal.xyz")
        assert result["match_found"] is False


class TestSearchPeopleTool:
    def setup_method(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(mcp, credentials=cred)
        self._fns = fns

    def _fn(self, name):
        return next(f for f in self._fns if f.__name__ == name)

    async def test_search_people_success(self):
        r = _mock_response(200, {
            "pagination": {"total_entries": 100},
            "people": [{"id": "p1", "first_name": "Alice", "last_name": "X",
                        "name": "Alice", "title": "VP Sales", "email": None,
                        "email_status": None, "linkedin_url": None,
                        "city": None, "state": None, "country": None,
                        "seniority": None, "organization": None}],
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self._fn("apollo_search_people")(titles=["VP Sales"])
        assert result["total"] == 100
        assert len(result["results"]) == 1

    async def test_search_people_with_all_filters(self):
        r = _mock_response(200, {"pagination": {}, "people": []})
        mock_client = _mock_async_client(r)
        with patch("httpx.AsyncClient", return_value=mock_client):
            await self._fn("apollo_search_people")(
                titles=["CEO"], seniorities=["c_suite"], locations=["San Francisco"],
                company_sizes=["51-200"], industries=["technology"],
                technologies=["salesforce"], limit=25,
            )
        call_json = mock_client.post.call_args.kwargs["json"]
        assert call_json["person_titles"] == ["CEO"]
        assert call_json["person_seniorities"] == ["c_suite"]
        assert call_json["person_locations"] == ["San Francisco"]
        assert call_json["organization_num_employees_ranges"] == ["51-200"]


class TestSearchCompaniesTool:
    def setup_method(self):
        fns = []
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(mcp, credentials=cred)
        self._fns = fns

    def _fn(self, name):
        return next(f for f in self._fns if f.__name__ == name)

    async def test_search_companies_success(self):
        r = _mock_response(200, {
            "pagination": {"total_entries": 50},
            "organizations": [{"id": "o1", "name": "Tech Corp",
                               "primary_domain": "tc.io", "website_url": None,
                               "linkedin_url": None, "industry": "Technology",
                               "estimated_num_employees": None,
                               "employee_count_range": None,
                               "annual_revenue_printed": None, "city": None,
                               "state": None, "country": None,
                               "short_description": None}],
        })
        with patch("httpx.AsyncClient", return_value=_mock_async_client(r)):
            result = await self._fn("apollo_search_companies")(industries=["technology"])
        assert result["total"] == 50
        assert result["results"][0]["industry"] == "Technology"

    async def test_search_companies_with_all_filters(self):
        r = _mock_response(200, {"pagination": {}, "organizations": []})
        mock_client = _mock_async_client(r)
        with patch("httpx.AsyncClient", return_value=mock_client):
            await self._fn("apollo_search_companies")(
                industries=["finance"], employee_counts=["201-500"],
                locations=["New York"], technologies=["aws"], limit=15,
            )
        call_json = mock_client.post.call_args.kwargs["json"]
        assert call_json["organization_industry_tag_ids"] == ["finance"]
        assert call_json["organization_num_employees_ranges"] == ["201-500"]
        assert call_json["organization_locations"] == ["New York"]
        assert call_json["currently_using_any_of_technology_uids"] == ["aws"]
        assert call_json["per_page"] == 15


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_apollo_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS
        assert "apollo" in CREDENTIAL_SPECS

    def test_apollo_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS
        assert CREDENTIAL_SPECS["apollo"].env_var == "APOLLO_API_KEY"

    def test_apollo_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS
        spec = CREDENTIAL_SPECS["apollo"]
        expected = {
            "apollo_enrich_person", "apollo_enrich_company", "apollo_search_people",
            "apollo_search_companies", "apollo_get_person_activities",
            "apollo_list_email_accounts", "apollo_bulk_enrich_people",
        }
        assert expected == set(spec.tools)
