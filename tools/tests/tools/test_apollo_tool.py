"""
Tests for Apollo.io data enrichment tool.

Covers:
- _ApolloClient methods (enrich_person, enrich_company, search_people, search_companies)
- Error handling (401, 403, 404, 422, 429, 500, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 4 MCP tool functions
- "Not found" graceful handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.apollo_tool.apollo_tool import (
    APOLLO_API_BASE,
    _ApolloClient,
    register_tools,
)

# --- _ApolloClient tests ---


class TestApolloClient:
    def setup_method(self):
        self.client = _ApolloClient("test-api-key")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        # API key is passed in X-Api-Key header
        assert headers["X-Api-Key"] == "test-api-key"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"person": {"id": "123"}}
        assert self.client._handle_response(response) == {"person": {"id": "123"}}

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
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"error": "Test error"}
        response.text = "Test error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"error": "Internal Server Error"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_by_email(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "person": {
                "id": "p123",
                "first_name": "John",
                "last_name": "Doe",
                "name": "John Doe",
                "title": "VP Sales",
                "email": "john@acme.com",
                "email_status": "verified",
                "phone_numbers": [{"sanitized_number": "+1234567890"}],
                "linkedin_url": "https://linkedin.com/in/johndoe",
                "twitter_url": None,
                "city": "San Francisco",
                "state": "California",
                "country": "United States",
                "organization": {
                    "id": "o456",
                    "name": "Acme Inc",
                    "primary_domain": "acme.com",
                    "industry": "Technology",
                    "estimated_num_employees": 250,
                },
            }
        }
        mock_post.return_value = mock_response

        result = self.client.enrich_person(email="john@acme.com")

        mock_post.assert_called_once_with(
            f"{APOLLO_API_BASE}/people/match",
            headers=self.client._headers,
            params=None,
            json={
                "email": "john@acme.com",
                "reveal_personal_emails": False,
                "reveal_phone_number": False,
            },
            timeout=30.0,
        )
        assert result["match_found"] is True
        assert result["person"]["first_name"] == "John"
        assert result["person"]["title"] == "VP Sales"
        assert result["person"]["organization"]["name"] == "Acme Inc"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_by_linkedin(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "person": {
                "id": "p456",
                "first_name": "Jane",
                "last_name": "Smith",
                "name": "Jane Smith",
                "title": "CTO",
                "email": "jane@startup.io",
                "linkedin_url": "https://linkedin.com/in/janesmith",
                "organization": {},
            }
        }
        mock_post.return_value = mock_response

        result = self.client.enrich_person(linkedin_url="https://linkedin.com/in/janesmith")

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["linkedin_url"] == "https://linkedin.com/in/janesmith"
        assert result["match_found"] is True
        assert result["person"]["title"] == "CTO"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_by_name_and_domain(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": {"id": "p123"}}
        mock_post.return_value = mock_response

        self.client.enrich_person(name="John Doe", domain="acme.com")

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["name"] == "John Doe"
        assert call_json["domain"] == "acme.com"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_with_reveal_flags(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": {"id": "p123"}}
        mock_post.return_value = mock_response

        self.client.enrich_person(
            email="john@acme.com",
            reveal_personal_emails=True,
            reveal_phone_number=True,
        )

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["reveal_personal_emails"] is True
        assert call_json["reveal_phone_number"] is True

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_with_optional_params(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": {"id": "p789"}}
        mock_post.return_value = mock_response

        self.client.enrich_person(
            email="john@acme.com",
            first_name="John",
            last_name="Doe",
            domain="acme.com",
        )

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["email"] == "john@acme.com"
        assert call_json["first_name"] == "John"
        assert call_json["last_name"] == "Doe"
        assert call_json["domain"] == "acme.com"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_not_found(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"person": None}
        mock_post.return_value = mock_response

        result = self.client.enrich_person(email="nobody@nowhere.xyz")

        assert result["match_found"] is False
        assert "No matching person found" in result["message"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_company(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organization": {
                "id": "o123",
                "name": "OpenAI",
                "primary_domain": "openai.com",
                "website_url": "https://openai.com",
                "linkedin_url": "https://linkedin.com/company/openai",
                "industry": "Artificial Intelligence",
                "keywords": ["ai", "machine learning", "gpt"],
                "estimated_num_employees": 1500,
                "employee_count_range": "1001-5000",
                "annual_revenue": 1000000000,
                "annual_revenue_printed": "$1B",
                "total_funding": 11000000000,
                "total_funding_printed": "$11B",
                "latest_funding_round_date": "2023-01-23",
                "latest_funding_stage": "Series D",
                "founded_year": 2015,
                "phone": "+1-415-123-4567",
                "city": "San Francisco",
                "state": "California",
                "country": "United States",
                "street_address": "123 Mission St",
                "technologies": ["python", "kubernetes", "aws"],
                "short_description": "AI research and deployment company",
            }
        }
        mock_post.return_value = mock_response

        result = self.client.enrich_company("openai.com")

        mock_post.assert_called_once_with(
            f"{APOLLO_API_BASE}/organizations/enrich",
            headers=self.client._headers,
            json={"domain": "openai.com"},
            timeout=30.0,
        )
        assert result["match_found"] is True
        assert result["organization"]["name"] == "OpenAI"
        assert result["organization"]["industry"] == "Artificial Intelligence"
        assert result["organization"]["employee_count"] == 1500
        assert "python" in result["organization"]["technologies"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_company_not_found(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"organization": None}
        mock_post.return_value = mock_response

        result = self.client.enrich_company("notarealcompany12345.xyz")

        assert result["match_found"] is False
        assert "No matching company found" in result["message"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_people(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "pagination": {"total_entries": 150, "page": 1, "per_page": 10},
            "people": [
                {
                    "id": "p1",
                    "first_name": "Alice",
                    "last_name": "Johnson",
                    "name": "Alice Johnson",
                    "title": "VP Sales",
                    "email": "alice@company.com",
                    "email_status": "verified",
                    "linkedin_url": "https://linkedin.com/in/alicejohnson",
                    "city": "New York",
                    "state": "New York",
                    "country": "United States",
                    "seniority": "vp",
                    "organization": {
                        "id": "o1",
                        "name": "Company Inc",
                        "primary_domain": "company.com",
                    },
                },
                {
                    "id": "p2",
                    "first_name": "Bob",
                    "last_name": "Smith",
                    "name": "Bob Smith",
                    "title": "Director of Sales",
                    "email": "bob@another.com",
                    "email_status": "verified",
                    "linkedin_url": "https://linkedin.com/in/bobsmith",
                    "city": "Chicago",
                    "state": "Illinois",
                    "country": "United States",
                    "seniority": "director",
                    "organization": None,
                },
            ],
        }
        mock_post.return_value = mock_response

        result = self.client.search_people(
            titles=["VP Sales", "Director of Sales"],
            seniorities=["vp", "director"],
            company_sizes=["51-200", "201-500"],
            limit=10,
        )

        mock_post.assert_called_once()
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["person_titles"] == ["VP Sales", "Director of Sales"]
        assert call_json["person_seniorities"] == ["vp", "director"]
        assert call_json["organization_num_employees_ranges"] == ["51-200", "201-500"]
        assert call_json["per_page"] == 10

        assert result["total"] == 150
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "VP Sales"
        assert result["results"][0]["organization"]["name"] == "Company Inc"
        # Bob has no organization
        assert result["results"][1]["organization"]["name"] is None

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_people_limit_capped(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pagination": {}, "people": []}
        mock_post.return_value = mock_response

        self.client.search_people(limit=200)

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["per_page"] == 100

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_companies(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "pagination": {"total_entries": 50, "page": 1, "per_page": 10},
            "organizations": [
                {
                    "id": "o1",
                    "name": "Tech Startup",
                    "primary_domain": "techstartup.io",
                    "website_url": "https://techstartup.io",
                    "linkedin_url": "https://linkedin.com/company/techstartup",
                    "industry": "Technology",
                    "estimated_num_employees": 75,
                    "employee_count_range": "51-200",
                    "annual_revenue_printed": "$10M",
                    "city": "Austin",
                    "state": "Texas",
                    "country": "United States",
                    "short_description": "A tech startup",
                },
            ],
        }
        mock_post.return_value = mock_response

        result = self.client.search_companies(
            industries=["technology"],
            employee_counts=["51-200"],
            technologies=["kubernetes"],
            limit=10,
        )

        mock_post.assert_called_once()
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["organization_industry_tag_ids"] == ["technology"]
        assert call_json["organization_num_employees_ranges"] == ["51-200"]
        assert call_json["currently_using_any_of_technology_uids"] == ["kubernetes"]

        assert result["total"] == 50
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "Tech Startup"
        assert result["results"][0]["industry"] == "Technology"


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 4

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        enrich_fn = next(fn for fn in registered_fns if fn.__name__ == "apollo_enrich_person")
        result = enrich_fn(email="test@test.com")
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "test-api-key"

        register_tools(mcp, credentials=cred_manager)

        enrich_fn = next(fn for fn in registered_fns if fn.__name__ == "apollo_enrich_company")

        with patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"organization": {"id": "123", "name": "Test"}}
            mock_post.return_value = mock_response

            result = enrich_fn(domain="test.com")

        cred_manager.get.assert_called_with("apollo")
        assert result["match_found"] is True

    def test_credentials_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        enrich_fn = next(fn for fn in registered_fns if fn.__name__ == "apollo_enrich_company")

        with (
            patch.dict("os.environ", {"APOLLO_API_KEY": "env-api-key"}),
            patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post") as mock_post,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"organization": {"id": "123", "name": "Test"}}
            mock_post.return_value = mock_response

            result = enrich_fn(domain="test.com")

        assert result["match_found"] is True
        # Verify API key was used in X-Api-Key header
        call_headers = mock_post.call_args.kwargs["headers"]
        assert call_headers["X-Api-Key"] == "env-api-key"


# --- Individual tool function tests ---


class TestEnrichPersonTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    def test_enrich_person_requires_email_or_linkedin(self):
        result = self._fn("apollo_enrich_person")()
        assert "error" in result
        assert "Invalid search criteria" in result["error"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "person": {
                        "id": "p1",
                        "first_name": "John",
                        "last_name": "Doe",
                        "title": "CEO",
                        "organization": {},
                    }
                }
            ),
        )
        result = self._fn("apollo_enrich_person")(email="john@acme.com")
        assert result["match_found"] is True
        assert result["person"]["title"] == "CEO"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("apollo_enrich_person")(email="test@test.com")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_person_network_error(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection failed")
        result = self._fn("apollo_enrich_person")(email="test@test.com")
        assert "error" in result
        assert "Network error" in result["error"]


class TestEnrichCompanyTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_company_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "organization": {
                        "id": "o1",
                        "name": "Acme Inc",
                        "industry": "Technology",
                        "estimated_num_employees": 500,
                    }
                }
            ),
        )
        result = self._fn("apollo_enrich_company")(domain="acme.com")
        assert result["match_found"] is True
        assert result["organization"]["name"] == "Acme Inc"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_enrich_company_not_found(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"organization": None})
        )
        result = self._fn("apollo_enrich_company")(domain="notreal.xyz")
        assert result["match_found"] is False


class TestSearchPeopleTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_people_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "pagination": {"total_entries": 100},
                    "people": [{"id": "p1", "name": "Alice", "title": "VP Sales"}],
                }
            ),
        )
        result = self._fn("apollo_search_people")(titles=["VP Sales"])
        assert result["total"] == 100
        assert len(result["results"]) == 1

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_people_with_all_filters(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"pagination": {}, "people": []})
        )
        self._fn("apollo_search_people")(
            titles=["CEO"],
            seniorities=["c_suite"],
            locations=["San Francisco"],
            company_sizes=["51-200"],
            industries=["technology"],
            technologies=["salesforce"],
            limit=25,
        )
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["person_titles"] == ["CEO"]
        assert call_json["person_seniorities"] == ["c_suite"]
        assert call_json["person_locations"] == ["San Francisco"]
        assert call_json["organization_num_employees_ranges"] == ["51-200"]


class TestSearchCompaniesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_companies_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "pagination": {"total_entries": 50},
                    "organizations": [{"id": "o1", "name": "Tech Corp", "industry": "Technology"}],
                }
            ),
        )
        result = self._fn("apollo_search_companies")(industries=["technology"])
        assert result["total"] == 50
        assert len(result["results"]) == 1
        assert result["results"][0]["industry"] == "Technology"

    @patch("aden_tools.tools.apollo_tool.apollo_tool.httpx.post")
    def test_search_companies_with_all_filters(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"pagination": {}, "organizations": []})
        )
        self._fn("apollo_search_companies")(
            industries=["finance"],
            employee_counts=["201-500"],
            locations=["New York"],
            technologies=["aws"],
            limit=15,
        )
        call_json = mock_post.call_args.kwargs["json"]
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

        spec = CREDENTIAL_SPECS["apollo"]
        assert spec.env_var == "APOLLO_API_KEY"

    def test_apollo_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["apollo"]
        assert "apollo_enrich_person" in spec.tools
        assert "apollo_enrich_company" in spec.tools
        assert "apollo_search_people" in spec.tools
        assert "apollo_search_companies" in spec.tools
        assert len(spec.tools) == 4
