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
        job_titles: list[str],
        location: str,
        seniority: str,
        industry: str | None = None,
        company_name: str | None = None,
        department: str | None = None,
    ) -> dict[str, Any]:
        """Search prospects via /prospecting/contact/search."""
        search_terms = [*job_titles, seniority]
        if industry:
            search_terms.append(industry)

        contact_include: dict[str, Any] = {
            "searchText": " ".join(s for s in search_terms if s).strip(),
            "locations": [{"country": location}],
        }
        if department:
            contact_include["departments"] = [department]

        company_include: dict[str, Any] = {}
        if company_name:
            company_include["names"] = [company_name]
        if industry:
            company_include["searchText"] = industry

        filters: dict[str, Any] = {"contacts": {"include": contact_include}}
        if company_include:
            filters["companies"] = {"include": company_include}

        body: dict[str, Any] = {
            "pages": {"size": 25, "page": 0},
            "filters": filters,
        }
        return self._request("POST", "/prospecting/contact/search", body=body)

    def search_companies(
        self,
        industry: str,
        employee_size: str,
        location: str,
    ) -> dict[str, Any]:
        """Search companies via /prospecting/company/search."""
        size_range: list[dict[str, int]] = []
        parts = employee_size.split("-", maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            size_range = [{"min": int(parts[0]), "max": int(parts[1])}]

        body: dict[str, Any] = {
            "pages": {"size": 25, "page": 0},
            "filters": {
                "companies": {
                    "include": {
                        "searchText": industry,
                        "sizes": size_range,
                        "locations": [{"country": location}],
                    }
                }
            },
        }
        return self._request("POST", "/prospecting/company/search", body=body)

    def get_signals(self, entity_type: str, ids: list[str]) -> dict[str, Any]:
        """Get contact/company signals by IDs."""
        if entity_type not in {"contact", "company"}:
            return {"error": "entity_type must be one of: contact, company"}
        if not ids:
            return {"error": "ids must contain at least one value"}

        try:
            numeric_ids = [int(v) for v in ids]
        except (TypeError, ValueError):
            return {"error": "ids must be numeric Lusha IDs"}

        if entity_type == "contact":
            return self._request(
                "POST",
                "/api/signals/contacts",
                body={"contactIds": numeric_ids, "signals": ["allSignals"]},
            )
        return self._request(
            "POST",
            "/api/signals/companies",
            body={
                "companyIds": numeric_ids,
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
                raise TypeError(
                    f"Expected string from credentials.get('lusha'), got {type(api_key).__name__}"
                )
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
        job_titles: list[str],
        location: str,
        seniority: str,
        industry: str | None = None,
        company_name: str | None = None,
        department: str | None = None,
    ) -> dict:
        """
        Search prospects using role/location/seniority filters.

        Args:
            job_titles: List of target job titles
            location: Target location
            seniority: Seniority level
            industry: Optional industry filter
            company_name: Optional company name filter
            department: Optional department filter

        Returns:
            Matching contact list payload (including IDs) or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.search_people(
                job_titles=job_titles,
                location=location,
                seniority=seniority,
                industry=industry,
                company_name=company_name,
                department=department,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_search_companies(
        industry: str,
        employee_size: str,
        location: str,
    ) -> dict:
        """
        Search companies using firmographic filters.

        Args:
            industry: Industry filter
            employee_size: Employee size range
            location: Company location filter

        Returns:
            Matching company list payload or error dict.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.search_companies(
                industry=industry,
                employee_size=employee_size,
                location=location,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def lusha_get_signals(entity_type: str, ids: list[str]) -> dict:
        """
        Retrieve signals/details for contacts or companies by IDs.

        Args:
            entity_type: "contact" or "company"
            ids: List of Lusha contact/company IDs

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
