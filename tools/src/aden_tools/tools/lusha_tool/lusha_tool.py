"""
Lusha Tool - B2B contact and company enrichment via Lusha API.

Supports:
- API key authentication (LUSHA_API_KEY)
- Credential store via CredentialStoreAdapter

API Reference: https://docs.lusha.com/apis/openapi

Tools:
- lusha_enrich_person
- lusha_enrich_company
- lusha_search_people
- lusha_search_companies
- lusha_get_signals
- lusha_get_account_usage
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

LUSHA_API_BASE = "https://api.lusha.com"


class _LushaClient:
    """Internal client wrapping Lusha API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "api_key": self._api_key,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to Lusha API."""
        response = httpx.request(
            method,
            f"{LUSHA_API_BASE}{path}",
            headers=self._headers,
            params=params or {},
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Normalize common API errors into stable tool responses."""
        if response.status_code == 401:
            return {"error": "Invalid Lusha API key"}
        if response.status_code == 403:
            return {
                "error": "Lusha API access forbidden. Check plan permissions and API access.",
                "help": "Verify API access in your Lusha account and workspace settings.",
            }
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {
                "error": "Lusha rate/credit limit reached. Try again later.",
                "help": "Review your Lusha plan credits and API rate limits.",
            }
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"Lusha API error (HTTP {response.status_code}): {detail}"}

        try:
            return response.json()
        except Exception:
            return {"error": "Lusha API returned a non-JSON response"}

    def enrich_person(
        self,
        email: str | None = None,
        linkedin_url: str | None = None,
    ) -> dict[str, Any]:
        """Enrich a person via /v2/person using email or LinkedIn URL."""
        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if linkedin_url:
            params["linkedinUrl"] = linkedin_url
        return self._request("GET", "/v2/person", params=params)

    def enrich_company(self, domain: str) -> dict[str, Any]:
        """Enrich a company via /v2/company by domain."""
        return self._request("GET", "/v2/company", params={"domain": domain})

    def search_people(
        self,
        *,
        job_titles: list[str] | None = None,
        seniority: list[int] | None = None,
        departments: list[str] | None = None,
        locations: list[dict[str, str]] | None = None,
        company_names: list[str] | None = None,
        industry_ids: list[int] | None = None,
        search_text: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search prospects via /prospecting/contact/search."""
        contact_include: dict[str, Any] = {}
        if job_titles:
            contact_include["jobTitles"] = job_titles
        if seniority:
            contact_include["seniority"] = seniority
        if departments:
            contact_include["departments"] = departments
        if locations:
            contact_include["locations"] = locations
        if search_text:
            contact_include["searchText"] = search_text

        company_include: dict[str, Any] = {}
        if company_names:
            company_include["names"] = company_names
        if industry_ids:
            company_include["mainIndustriesIds"] = industry_ids

        filters: dict[str, Any] = {}
        if contact_include:
            filters["contacts"] = {"include": contact_include}
        if company_include:
            filters["companies"] = {"include": company_include}

        body: dict[str, Any] = {
            "pages": {"size": max(10, min(limit, 50)), "page": 0},
            "filters": filters,
        }
        return self._request("POST", "/prospecting/contact/search", body=body)

    def search_companies(
        self,
        *,
        industry_ids: list[int] | None = None,
        employee_size: str | None = None,
        locations: list[dict[str, str]] | None = None,
        company_names: list[str] | None = None,
        search_text: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search companies via /prospecting/company/search."""
        company_include: dict[str, Any] = {}

        if employee_size:
            parts = employee_size.split("-", maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                company_include["sizes"] = [{"min": int(parts[0]), "max": int(parts[1])}]

        if locations:
            company_include["locations"] = locations
        if industry_ids:
            company_include["mainIndustriesIds"] = industry_ids
        if company_names:
            company_include["names"] = company_names
        if search_text:
            company_include["searchText"] = search_text

        body: dict[str, Any] = {
            "pages": {"size": max(10, min(limit, 50)), "page": 0},
            "filters": {
                "companies": {
                    "include": company_include,
                }
            },
        }
        return self._request("POST", "/prospecting/company/search", body=body)

    def get_signals(self, entity_type: str, ids: list[int]) -> dict[str, Any]:
        """Get contact/company signals by IDs."""
        if entity_type not in {"contact", "company"}:
            return {"error": "entity_type must be one of: contact, company"}
        if not ids:
            return {"error": "ids must contain at least one value"}

        if entity_type == "contact":
            return self._request(
                "POST",
                "/api/signals/contacts",
                body={"contactIds": ids, "signals": ["allSignals"]},
            )
        return self._request(
            "POST",
            "/api/signals/companies",
            body={
                "companyIds": ids,
                "signals": ["allSignals"],
            },
        )

    def get_account_usage(self) -> dict[str, Any]:
        """Get account credit usage via /account/usage."""
        return self._request("GET", "/account/usage")


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Lusha tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Lusha API key from credential store or environment."""
        if credentials is not None:
            api_key = credentials.get("lusha")
            if api_key is not None and not isinstance(api_key, str):
                return None
            return api_key
        return os.getenv("LUSHA_API_KEY")

    def _get_client() -> _LushaClient | dict[str, str]:
        """Get a Lusha client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Lusha credentials not configured",
                "help": (
                    "Set LUSHA_API_KEY environment variable or configure via credential store. "
                    "Open docs at https://docs.lusha.com/apis/openapi"
                ),
            }
        return _LushaClient(api_key)

    @mcp.tool()
    def lusha_enrich_person(
        email: str | None = None,
        linkedin_url: str | None = None,
    ) -> dict:
        """
        Enrich contact by email or LinkedIn URL.

        Args:
            email: Contact email
            linkedin_url: Contact LinkedIn profile URL

        Returns:
            Lusha contact enrichment payload or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not email and not linkedin_url:
            return {"error": "Provide at least one of: email, linkedin_url"}

        try:
            return client.enrich_person(email=email, linkedin_url=linkedin_url)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_enrich_company(domain: str) -> dict:
        """
        Enrich company by domain.

        Args:
            domain: Company domain (e.g. "openai.com")

        Returns:
            Lusha company enrichment payload or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.enrich_company(domain=domain)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_search_people(
        job_titles: list[str] | None = None,
        seniority: list[int] | None = None,
        departments: list[str] | None = None,
        locations: list[dict[str, str]] | None = None,
        company_names: list[str] | None = None,
        industry_ids: list[int] | None = None,
        search_text: str | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search prospects using structured Lusha filters.

        Args:
            job_titles: Job title keywords (e.g. ["CTO", "VP Engineering"])
            seniority: Seniority level IDs (e.g. [9, 10] for c-suite/founder).
                Known IDs: 10=founder, 9=c-suite, 8=vp, 7=director, 6=manager,
                5=senior, 4=entry. Refer to Lusha API docs for the full mapping.
            departments: Department names (e.g. ["Engineering & Technical"])
            locations: Location filters, each a dict with optional keys:
                country, state, city, continent (e.g. [{"country": "United States"}])
            company_names: Filter by company names (e.g. ["OpenAI", "Google"])
            industry_ids: Lusha mainIndustriesIds (numeric). Refer to Lusha API
                docs for the ID-to-industry mapping.
            search_text: Optional free-text search across contact fields
            limit: Max results to return (10-50, default 10)

        Returns:
            Matching contact list payload (including IDs) or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.search_people(
                job_titles=job_titles,
                seniority=seniority,
                departments=departments,
                locations=locations,
                company_names=company_names,
                industry_ids=industry_ids,
                search_text=search_text,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_search_companies(
        employee_size: str | None = None,
        locations: list[dict[str, str]] | None = None,
        industry_ids: list[int] | None = None,
        company_names: list[str] | None = None,
        search_text: str | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search companies using firmographic filters.

        Args:
            employee_size: Employee size range (e.g. "51-200")
            locations: Location filters, each a dict with optional keys:
                country, state, city, continent (e.g. [{"country": "United States"}])
            industry_ids: Lusha mainIndustriesIds (numeric). Refer to Lusha API
                docs for the ID-to-industry mapping.
            company_names: Filter by company names (e.g. ["Apple", "Microsoft"])
            search_text: Optional free-text search across company fields
            limit: Max results to return (10-50, default 10)

        Returns:
            Matching company list payload or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.search_companies(
                industry_ids=industry_ids,
                employee_size=employee_size,
                locations=locations,
                company_names=company_names,
                search_text=search_text,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_get_signals(entity_type: str, ids: list[int]) -> dict:
        """
        Retrieve signals/details for contacts or companies by IDs.

        Args:
            entity_type: "contact" or "company"
            ids: List of numeric Lusha contact/company IDs

        Returns:
            Signal/detail payload for requested entities, or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_signals(entity_type=entity_type, ids=ids)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_get_account_usage() -> dict:
        """
        Retrieve account usage and credits.

        Returns:
            Account usage payload or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_account_usage()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
