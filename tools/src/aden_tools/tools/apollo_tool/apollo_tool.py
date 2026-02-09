"""
Apollo.io Tool - Contact and company data enrichment via Apollo API.

Supports:
- API key authentication (APOLLO_API_KEY)

Use Cases:
- Enrich contacts by email or LinkedIn URL
- Enrich companies by domain
- Search for people by titles, seniorities, locations
- Search for companies by industries, employee counts, technologies

API Reference: https://apolloio.github.io/apollo-api-docs/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

APOLLO_API_BASE = "https://api.apollo.io/api/v1"


class _ApolloClient:
    """Internal client wrapping Apollo.io API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self._api_key,
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Apollo API key"}
        if response.status_code == 403:
            return {
                "error": "Insufficient credits or permissions. Check your Apollo plan.",
                "help": "Apollo uses export credits for enrichment. Visit https://app.apollo.io/#/settings/plans",
            }
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 422:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid parameters: {detail}"}
        if response.status_code == 429:
            return {"error": "Apollo rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Apollo API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def enrich_person(
        self,
        email: str | None = None,
        linkedin_url: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        name: str | None = None,
        domain: str | None = None,
        reveal_personal_emails: bool = False,
        reveal_phone_number: bool = False,
    ) -> dict[str, Any]:
        """Enrich a person by email, LinkedIn URL, or name and domain."""
        body: dict[str, Any] = {
            "reveal_personal_emails": reveal_personal_emails,
            "reveal_phone_number": reveal_phone_number,
        }

        if email:
            body["email"] = email
        if linkedin_url:
            body["linkedin_url"] = linkedin_url
        if first_name:
            body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        if name:
            body["name"] = name
        if domain:
            body["domain"] = domain

        response = httpx.post(
            f"{APOLLO_API_BASE}/people/match",
            headers=self._headers,
            params=body if not email and not linkedin_url else None,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        # Handle "not found" gracefully
        if "error" not in result and result.get("person") is None:
            return {"match_found": False, "message": "No matching person found"}

        if "error" not in result:
            person = result.get("person", {})
            return {
                "match_found": True,
                "person": {
                    "id": person.get("id"),
                    "first_name": person.get("first_name"),
                    "last_name": person.get("last_name"),
                    "name": person.get("name"),
                    "title": person.get("title"),
                    "email": person.get("email"),
                    "email_status": person.get("email_status"),
                    "phone_numbers": person.get("phone_numbers", []),
                    "linkedin_url": person.get("linkedin_url"),
                    "twitter_url": person.get("twitter_url"),
                    "city": person.get("city"),
                    "state": person.get("state"),
                    "country": person.get("country"),
                    "organization": {
                        "id": person.get("organization", {}).get("id"),
                        "name": person.get("organization", {}).get("name"),
                        "domain": person.get("organization", {}).get("primary_domain"),
                        "industry": person.get("organization", {}).get("industry"),
                        "employee_count": person.get("organization", {}).get(
                            "estimated_num_employees"
                        ),
                    },
                },
            }
        return result

    def enrich_company(self, domain: str) -> dict[str, Any]:
        """Enrich a company by domain."""
        body: dict[str, Any] = {
            "domain": domain,
        }

        response = httpx.post(
            f"{APOLLO_API_BASE}/organizations/enrich",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        # Handle "not found" gracefully
        if "error" not in result and result.get("organization") is None:
            return {"match_found": False, "message": "No matching company found"}

        if "error" not in result:
            org = result.get("organization", {})
            return {
                "match_found": True,
                "organization": {
                    "id": org.get("id"),
                    "name": org.get("name"),
                    "domain": org.get("primary_domain"),
                    "website_url": org.get("website_url"),
                    "linkedin_url": org.get("linkedin_url"),
                    "twitter_url": org.get("twitter_url"),
                    "facebook_url": org.get("facebook_url"),
                    "industry": org.get("industry"),
                    "keywords": org.get("keywords", []),
                    "employee_count": org.get("estimated_num_employees"),
                    "employee_count_range": org.get("employee_count_range"),
                    "annual_revenue": org.get("annual_revenue"),
                    "annual_revenue_printed": org.get("annual_revenue_printed"),
                    "total_funding": org.get("total_funding"),
                    "total_funding_printed": org.get("total_funding_printed"),
                    "latest_funding_round_date": org.get("latest_funding_round_date"),
                    "latest_funding_stage": org.get("latest_funding_stage"),
                    "founded_year": org.get("founded_year"),
                    "phone": org.get("phone"),
                    "city": org.get("city"),
                    "state": org.get("state"),
                    "country": org.get("country"),
                    "street_address": org.get("street_address"),
                    "technologies": org.get("technologies", []),
                    "short_description": org.get("short_description"),
                },
            }
        return result

    def search_people(
        self,
        titles: list[str] | None = None,
        seniorities: list[str] | None = None,
        locations: list[str] | None = None,
        company_sizes: list[str] | None = None,
        industries: list[str] | None = None,
        technologies: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for people with filters."""
        body: dict[str, Any] = {
            "per_page": min(limit, 100),
            "page": 1,
        }

        if titles:
            body["person_titles"] = titles
        if seniorities:
            body["person_seniorities"] = seniorities
        if locations:
            body["person_locations"] = locations
        if company_sizes:
            body["organization_num_employees_ranges"] = company_sizes
        if industries:
            body["organization_industry_tag_ids"] = industries
        if technologies:
            body["currently_using_any_of_technology_uids"] = technologies

        response = httpx.post(
            f"{APOLLO_API_BASE}/mixed_people/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            people = result.get("people", [])
            return {
                "total": result.get("pagination", {}).get("total_entries", len(people)),
                "page": result.get("pagination", {}).get("page", 1),
                "per_page": result.get("pagination", {}).get("per_page", limit),
                "results": [
                    {
                        "id": p.get("id"),
                        "first_name": p.get("first_name"),
                        "last_name": p.get("last_name"),
                        "name": p.get("name"),
                        "title": p.get("title"),
                        "email": p.get("email"),
                        "email_status": p.get("email_status"),
                        "linkedin_url": p.get("linkedin_url"),
                        "city": p.get("city"),
                        "state": p.get("state"),
                        "country": p.get("country"),
                        "seniority": p.get("seniority"),
                        "organization": {
                            "id": p.get("organization", {}).get("id")
                            if p.get("organization")
                            else None,
                            "name": p.get("organization", {}).get("name")
                            if p.get("organization")
                            else None,
                            "domain": p.get("organization", {}).get("primary_domain")
                            if p.get("organization")
                            else None,
                        },
                    }
                    for p in people
                ],
            }
        return result

    def search_companies(
        self,
        industries: list[str] | None = None,
        employee_counts: list[str] | None = None,
        locations: list[str] | None = None,
        technologies: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for companies with filters."""
        body: dict[str, Any] = {
            "per_page": min(limit, 100),
            "page": 1,
        }

        if industries:
            body["organization_industry_tag_ids"] = industries
        if employee_counts:
            body["organization_num_employees_ranges"] = employee_counts
        if locations:
            body["organization_locations"] = locations
        if technologies:
            body["currently_using_any_of_technology_uids"] = technologies

        response = httpx.post(
            f"{APOLLO_API_BASE}/mixed_companies/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            orgs = result.get("organizations", [])
            return {
                "total": result.get("pagination", {}).get("total_entries", len(orgs)),
                "page": result.get("pagination", {}).get("page", 1),
                "per_page": result.get("pagination", {}).get("per_page", limit),
                "results": [
                    {
                        "id": o.get("id"),
                        "name": o.get("name"),
                        "domain": o.get("primary_domain"),
                        "website_url": o.get("website_url"),
                        "linkedin_url": o.get("linkedin_url"),
                        "industry": o.get("industry"),
                        "employee_count": o.get("estimated_num_employees"),
                        "employee_count_range": o.get("employee_count_range"),
                        "annual_revenue_printed": o.get("annual_revenue_printed"),
                        "city": o.get("city"),
                        "state": o.get("state"),
                        "country": o.get("country"),
                        "short_description": o.get("short_description"),
                    }
                    for o in orgs
                ],
            }
        return result


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Apollo.io data enrichment tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Apollo API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("apollo")
            # Defensive check: ensure we get a string, not a complex object
            if api_key is not None and not isinstance(api_key, str):
                raise TypeError(
                    f"Expected string from credentials.get('apollo'), got {type(api_key).__name__}"
                )
            return api_key
        return os.getenv("APOLLO_API_KEY")

    def _get_client() -> _ApolloClient | dict[str, str]:
        """Get an Apollo client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Apollo credentials not configured",
                "help": (
                    "Set APOLLO_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get your API key at https://app.apollo.io/#/settings/integrations/api"
                ),
            }
        return _ApolloClient(api_key)

    # --- Person Enrichment ---

    @mcp.tool()
    def apollo_enrich_person(
        email: str | None = None,
        linkedin_url: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        name: str | None = None,
        domain: str | None = None,
        reveal_personal_emails: bool = False,
        reveal_phone_number: bool = False,
    ) -> dict:
        """
        Enrich a person's information by email, LinkedIn URL, or name and domain.

        Args:
            email: Person's email address
            linkedin_url: Person's LinkedIn profile URL
            first_name: Person's first name (use with last_name and domain)
            last_name: Person's last name (use with first_name and domain)
            name: Person's full name (use with domain)
            domain: Person's company domain (e.g., "acme.com")
            reveal_personal_emails: Whether to reveal personal email addresses (default: False)
            reveal_phone_number: Whether to reveal phone numbers (default: False)

        Returns:
            Dict with person details including:
            - Full name, title
            - Email and email status
            - Phone numbers (if revealed)
            - Location (city, state, country)
            - LinkedIn/Twitter URLs
            - Company info (name, industry, size)
            Or error dict if enrichment fails

        Example:
            apollo_enrich_person(email="john@acme.com")
            apollo_enrich_person(name="John Doe", domain="acme.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        # Validate that we have enough info to match
        has_email_or_linkedin = bool(email or linkedin_url)
        has_name_and_domain = bool((first_name and last_name and domain) or (name and domain))

        if not has_email_or_linkedin and not has_name_and_domain:
            return {
                "error": (
                    "Invalid search criteria. Provide either (email), (linkedin_url), "
                    "or (name/first_name+last_name AND domain)."
                )
            }
        try:
            return client.enrich_person(
                email=email,
                linkedin_url=linkedin_url,
                first_name=first_name,
                last_name=last_name,
                name=name,
                domain=domain,
                reveal_personal_emails=reveal_personal_emails,
                reveal_phone_number=reveal_phone_number,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Company Enrichment ---

    @mcp.tool()
    def apollo_enrich_company(domain: str) -> dict:
        """
        Enrich a company by domain.

        Args:
            domain: Company domain (e.g., "acme.com")

        Returns:
            Dict with company firmographics including:
            - name, domain, website URL
            - Industry, keywords
            - Employee count and range
            - Annual revenue, funding info
            - Founded year, location
            - Technologies used
            Or error dict if enrichment fails

        Example:
            apollo_enrich_company(domain="openai.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.enrich_company(domain)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- People Search ---

    @mcp.tool()
    def apollo_search_people(
        titles: list[str] | None = None,
        seniorities: list[str] | None = None,
        locations: list[str] | None = None,
        company_sizes: list[str] | None = None,
        industries: list[str] | None = None,
        technologies: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search for contacts with filters.

        Args:
            titles: Job titles to search for
                (e.g., ["VP Sales", "Director of Marketing"])
            seniorities: Seniority levels
                (e.g., ["vp", "director", "c_suite", "manager", "senior"])
            locations: Geographic locations
                (e.g., ["San Francisco, CA", "New York, NY"])
            company_sizes: Company employee count ranges
                (e.g., ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000"])
            industries: Industry tags
                (e.g., ["technology", "finance", "healthcare"])
            technologies: Technologies used by company
                (e.g., ["salesforce", "hubspot", "aws"])
            limit: Maximum results (1-100, default 10)

        Returns:
            Dict with:
            - total: Total matching results
            - results: List of matching contacts with email and company info
            Or error dict if search fails

        Example:
            apollo_search_people(
                titles=["VP Sales", "Head of Sales"],
                seniorities=["vp", "director"],
                company_sizes=["51-200", "201-500"],
                limit=25
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search_people(
                titles=titles,
                seniorities=seniorities,
                locations=locations,
                company_sizes=company_sizes,
                industries=industries,
                technologies=technologies,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Company Search ---

    @mcp.tool()
    def apollo_search_companies(
        industries: list[str] | None = None,
        employee_counts: list[str] | None = None,
        locations: list[str] | None = None,
        technologies: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search for companies with filters.

        Args:
            industries: Industry tags
                (e.g., ["technology", "finance", "healthcare"])
            employee_counts: Employee count ranges
                (e.g., ["1-10", "11-50", "51-200", "201-500", "501-1000"])
            locations: Geographic locations
                (e.g., ["San Francisco, CA", "United States"])
            technologies: Technologies used
                (e.g., ["salesforce", "hubspot", "aws", "kubernetes"])
            limit: Maximum results (1-100, default 10)

        Returns:
            Dict with:
            - total: Total matching results
            - results: List of matching companies with firmographic data
            Or error dict if search fails

        Example:
            apollo_search_companies(
                industries=["technology"],
                employee_counts=["51-200", "201-500"],
                technologies=["kubernetes"],
                limit=20
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search_companies(
                industries=industries,
                employee_counts=employee_counts,
                locations=locations,
                technologies=technologies,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
