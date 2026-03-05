"""Tests for lusha_tool - B2B contact and company enrichment."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.lusha_tool.lusha_tool import register_tools

ENV = {"LUSHA_API_KEY": "test-api-key"}


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


class TestLushaEnrichPerson:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["lusha_enrich_person"](first_name="Jane", last_name="Doe")
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["lusha_enrich_person"]()
        assert "error" in result

    def test_successful_enrich_by_name(self, tool_fns):
        data = {
            "firstName": "Jane",
            "lastName": "Doe",
            "fullName": "Jane Doe",
            "jobTitle": "CTO",
            "company": "Acme Inc",
            "emailAddresses": [{"email": "jane@acme.com", "emailType": "work"}],
            "phoneNumbers": [{"phone": "+1234567890", "phoneType": "mobile"}],
            "linkedinUrl": "https://linkedin.com/in/janedoe",
            "location": "San Francisco, CA",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_enrich_person"](
                first_name="Jane", last_name="Doe", company_domain="acme.com"
            )

        assert result["full_name"] == "Jane Doe"
        assert result["job_title"] == "CTO"
        assert len(result["email_addresses"]) == 1

    def test_successful_enrich_by_email(self, tool_fns):
        data = {
            "firstName": "Jane",
            "lastName": "Doe",
            "fullName": "Jane Doe",
            "jobTitle": "CTO",
            "company": "Acme Inc",
            "emailAddresses": [],
            "phoneNumbers": [],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_enrich_person"](email="jane@acme.com")

        assert result["first_name"] == "Jane"


class TestLushaEnrichCompany:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["lusha_enrich_company"]()
        assert "error" in result

    def test_successful_enrich(self, tool_fns):
        data = {
            "name": "Acme Inc",
            "domain": "acme.com",
            "industry": "Technology",
            "employeeCount": 500,
            "revenue": "$50M-$100M",
            "location": "San Francisco, CA",
            "description": "A tech company",
            "foundedYear": 2015,
            "technologies": ["Python", "AWS"],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_enrich_company"](domain="acme.com")

        assert result["name"] == "Acme Inc"
        assert result["employee_count"] == 500
        assert "Python" in result["technologies"]


class TestLushaSearchContacts:
    def test_missing_filters(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["lusha_search_contacts"]()
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "data": [
                {
                    "contactId": "abc-123",
                    "firstName": "John",
                    "lastName": "Smith",
                    "jobTitle": "VP Engineering",
                    "seniority": "VP",
                    "department": "Engineering",
                    "companyName": "Acme Inc",
                    "companyDomain": "acme.com",
                    "location": "New York",
                }
            ],
            "total": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_search_contacts"](
                seniorities="4,5", company_domains="acme.com"
            )

        assert result["count"] == 1
        assert result["contacts"][0]["first_name"] == "John"
        assert result["contacts"][0]["company_name"] == "Acme Inc"


class TestLushaSearchCompanies:
    def test_missing_filters(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["lusha_search_companies"]()
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "data": [
                {
                    "companyName": "Acme Inc",
                    "companyDomain": "acme.com",
                    "industry": "Technology",
                    "employeeCount": 500,
                    "revenue": "$50M-$100M",
                    "location": "SF",
                }
            ],
            "total": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_search_companies"](country="United States")

        assert result["count"] == 1
        assert result["companies"][0]["name"] == "Acme Inc"


class TestLushaGetUsage:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["lusha_get_usage"]()
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {"credits_used": 150, "credits_remaining": 850, "plan": "Professional"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.lusha_tool.lusha_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["lusha_get_usage"]()

        assert result["credits_used"] == 150
