"""
Vibe Prospecting Tool - B2B prospecting and data enrichment via Explorium API.

Supports:
- API key authentication (VIBEPROSPECTING_API_KEY)

Use Cases:
- Search and enrich companies by filters (industry, size, location, technology)
- Search and enrich prospects/contacts by job title, department, seniority
- Match companies and prospects for accurate entity resolution
- Get company statistics for market analysis
- Autocomplete for company search

API Reference: https://developers.explorium.ai/reference/introduction
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

VIBEPROSPECTING_API_BASE = "https://api.explorium.ai/v1"


class _VibeProspectingClient:
    """Internal client wrapping Vibe Prospecting (Explorium) API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "API_KEY": self._api_key,
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Vibe Prospecting API key"}
        if response.status_code == 403:
            return {
                "error": "Insufficient credits or permissions. Check your Vibe Prospecting plan.",
                "help": "Visit https://www.vibeprospecting.ai/pricing to upgrade your plan",
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
            return {
                "error": "Rate limit exceeded (200 queries per minute). Try again later.",
                "help": "Consider implementing request batching or contact support for higher limits",
            }
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Vibe Prospecting API error (HTTP {response.status_code}): {detail}"}

        try:
            return response.json()
        except Exception:
            return {"error": "Invalid JSON response from API"}

    def search_companies(
        self,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 10,
        mode: str = "full",
    ) -> dict[str, Any]:
        """Search for companies with filters."""
        body: dict[str, Any] = {
            "filters": filters,
            "page": page,
            "page_size": min(page_size, 100),
            "mode": mode,
        }

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/businesses",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def enrich_company(
        self,
        business_id: str | None = None,
        domain: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Enrich a company by business_id, domain, or name."""
        body: dict[str, Any] = {}

        if business_id:
            body["business_id"] = business_id
        elif domain:
            body["domain"] = domain
        elif name:
            body["name"] = name
        else:
            return {"error": "Must provide business_id, domain, or name"}

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/businesses/enrich",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def search_prospects(
        self,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 10,
        mode: str = "full",
    ) -> dict[str, Any]:
        """Search for prospects/contacts with filters."""
        body: dict[str, Any] = {
            "filters": filters,
            "page": page,
            "page_size": min(page_size, 100),
            "mode": mode,
        }

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/prospects",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def enrich_prospect(
        self,
        prospect_id: str | None = None,
        email: str | None = None,
        linkedin_url: str | None = None,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        """Enrich a prospect by prospect_id, email, LinkedIn URL, or name."""
        body: dict[str, Any] = {}

        if prospect_id:
            body["prospect_id"] = prospect_id
        elif email:
            body["email"] = email
        elif linkedin_url:
            body["linkedin_url"] = linkedin_url
        elif full_name:
            body["full_name"] = full_name
        else:
            return {"error": "Must provide prospect_id, email, linkedin_url, or full_name"}

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/prospects/enrich",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def match_company(
        self,
        name: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Match a company to get accurate business_id."""
        body: dict[str, Any] = {}

        if name:
            body["name"] = name
        if domain:
            body["domain"] = domain

        if not body:
            return {"error": "Must provide name or domain"}

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/businesses/match",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def match_prospect(
        self,
        email: str | None = None,
        linkedin_url: str | None = None,
        full_name: str | None = None,
        business_id: str | None = None,
    ) -> dict[str, Any]:
        """Match a prospect to get accurate prospect_id."""
        body: dict[str, Any] = {}

        if email:
            body["email"] = email
        if linkedin_url:
            body["linkedin_url"] = linkedin_url
        if full_name:
            body["full_name"] = full_name
        if business_id:
            body["business_id"] = business_id

        if not any([email, linkedin_url, full_name]):
            return {"error": "Must provide email, linkedin_url, or full_name"}

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/prospects/match",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def company_statistics(
        self,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """Get statistics for companies matching filters."""
        body: dict[str, Any] = {"filters": filters}

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/businesses/stats",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def autocomplete_company(
        self,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Autocomplete company search."""
        body: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 50),
        }

        response = httpx.post(
            f"{VIBEPROSPECTING_API_BASE}/businesses/autocomplete",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Vibe Prospecting data enrichment tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Vibe Prospecting API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("vibeprospecting")
            if api_key is not None and not isinstance(api_key, str):
                raise TypeError(
                    f"Expected string from credentials.get('vibeprospecting'), got {type(api_key).__name__}"
                )
            return api_key
        return os.getenv("VIBEPROSPECTING_API_KEY")

    def _get_client() -> _VibeProspectingClient | dict[str, str]:
        """Get a Vibe Prospecting client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Vibe Prospecting credentials not configured",
                "help": (
                    "Set VIBEPROSPECTING_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get your API key at https://www.vibeprospecting.ai/"
                ),
            }
        return _VibeProspectingClient(api_key)

    # --- Company Search & Enrichment ---

    @mcp.tool()
    def vibeprospecting_search_companies(
        filters_json: str,
        page: int = 1,
        page_size: int = 10,
        mode: str = "full",
    ) -> dict:
        """
        Search for companies with filters.

        Args:
            filters_json: JSON object with filter criteria. Example filters:
                - country_code: {"type": "includes", "values": ["us", "ca"]}
                - company_size: {"type": "includes", "values": ["11-50", "51-200"]}
                - industry: {"type": "includes", "values": ["software", "technology"]}
                - technologies: {"type": "includes", "values": ["salesforce", "aws"]}
                - annual_revenue_range: {"type": "includes", "values": ["1M-10M"]}
                - has_funding: {"value": true}
            page: Page number (default 1)
            page_size: Results per page, max 100 (default 10)
            mode: "full" for detailed data, "basic" for minimal (default "full")

        Returns:
            Dict with company results including:
            - business_id, name, domain
            - Industry, employee count, revenue
            - Location, funding info
            - Technologies used
            Or error dict if search fails

        Example:
            vibeprospecting_search_companies(
                filters_json='{"country_code": {"type": "includes", "values": ["us"]}, "company_size": {"type": "includes", "values": ["51-200"]}}',
                page_size=20
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            return {"error": "filters_json must be valid JSON"}

        try:
            return client.search_companies(
                filters=filters,
                page=page,
                page_size=page_size,
                mode=mode,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def vibeprospecting_enrich_company(
        business_id: str | None = None,
        domain: str | None = None,
        name: str | None = None,
    ) -> dict:
        """
        Enrich a company by business_id, domain, or name.

        Args:
            business_id: Vibe Prospecting business ID (most accurate)
            domain: Company domain (e.g., "tesla.com")
            name: Company name (less accurate, use with caution)

        Returns:
            Dict with enriched company data including:
            - Firmographics (size, revenue, industry)
            - Location and contact info
            - Funding and financial data
            - Technologies and keywords
            - Social profiles
            Or error dict if enrichment fails

        Example:
            vibeprospecting_enrich_company(domain="openai.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not any([business_id, domain, name]):
            return {"error": "Must provide business_id, domain, or name"}

        try:
            return client.enrich_company(
                business_id=business_id,
                domain=domain,
                name=name,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Prospect Search & Enrichment ---

    @mcp.tool()
    def vibeprospecting_search_prospects(
        filters_json: str,
        page: int = 1,
        page_size: int = 10,
        mode: str = "full",
    ) -> dict:
        """
        Search for prospects/contacts with filters.

        Args:
            filters_json: JSON object with filter criteria. Example filters:
                - business_id: {"values": ["business_id_here"]}
                - job_title: {"values": ["VP Sales", "Director Marketing"]}
                - job_level: {"values": ["director", "manager", "vp"]}
                - job_department: {"values": ["sales", "marketing", "engineering"]}
                - seniority: {"values": ["executive", "senior", "mid-level"]}
                - has_email: {"value": true}
                - has_phone: {"value": true}
                - country_code: {"type": "includes", "values": ["us"]}
            page: Page number (default 1)
            page_size: Results per page, max 100 (default 10)
            mode: "full" for detailed data, "basic" for minimal (default "full")

        Returns:
            Dict with prospect results including:
            - prospect_id, full_name, email, phone
            - Job title, level, department
            - Company info
            - LinkedIn and social profiles
            - Work history and skills
            Or error dict if search fails

        Example:
            vibeprospecting_search_prospects(
                filters_json='{"job_level": {"values": ["director", "vp"]}, "job_department": {"values": ["sales"]}, "has_email": {"value": true}}',
                page_size=25
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            return {"error": "filters_json must be valid JSON"}

        try:
            return client.search_prospects(
                filters=filters,
                page=page,
                page_size=page_size,
                mode=mode,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def vibeprospecting_enrich_prospect(
        prospect_id: str | None = None,
        email: str | None = None,
        linkedin_url: str | None = None,
        full_name: str | None = None,
    ) -> dict:
        """
        Enrich a prospect by prospect_id, email, LinkedIn URL, or name.

        Args:
            prospect_id: Vibe Prospecting prospect ID (most accurate)
            email: Prospect's email address
            linkedin_url: LinkedIn profile URL
            full_name: Full name of the prospect

        Returns:
            Dict with enriched prospect data including:
            - Contact details (email, phone, social profiles)
            - Current job (title, company, department)
            - Work history and career trajectory
            - Skills and expertise
            - Education background
            Or error dict if enrichment fails

        Example:
            vibeprospecting_enrich_prospect(email="john@acme.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not any([prospect_id, email, linkedin_url, full_name]):
            return {"error": "Must provide prospect_id, email, linkedin_url, or full_name"}

        try:
            return client.enrich_prospect(
                prospect_id=prospect_id,
                email=email,
                linkedin_url=linkedin_url,
                full_name=full_name,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Matching ---

    @mcp.tool()
    def vibeprospecting_match_company(
        name: str | None = None,
        domain: str | None = None,
    ) -> dict:
        """
        Match a company to get accurate business_id for enrichment.

        Use this before enrichment to ensure you're targeting the right entity.

        Args:
            name: Company name
            domain: Company domain (e.g., "acme.com")

        Returns:
            Dict with matched company data including business_id
            Or error dict if matching fails

        Example:
            vibeprospecting_match_company(domain="tesla.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not any([name, domain]):
            return {"error": "Must provide name or domain"}

        try:
            return client.match_company(name=name, domain=domain)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def vibeprospecting_match_prospect(
        email: str | None = None,
        linkedin_url: str | None = None,
        full_name: str | None = None,
        business_id: str | None = None,
    ) -> dict:
        """
        Match a prospect to get accurate prospect_id for enrichment.

        Use this before enrichment to ensure you're targeting the right person.

        Args:
            email: Prospect's email address
            linkedin_url: LinkedIn profile URL
            full_name: Full name of the prospect
            business_id: Optional business_id to narrow search

        Returns:
            Dict with matched prospect data including prospect_id
            Or error dict if matching fails

        Example:
            vibeprospecting_match_prospect(
                email="john@acme.com",
                business_id="matched_business_id"
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not any([email, linkedin_url, full_name]):
            return {"error": "Must provide email, linkedin_url, or full_name"}

        try:
            return client.match_prospect(
                email=email,
                linkedin_url=linkedin_url,
                full_name=full_name,
                business_id=business_id,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Statistics & Autocomplete ---

    @mcp.tool()
    def vibeprospecting_company_statistics(filters_json: str) -> dict:
        """
        Get statistics for companies matching filters.

        Use this to gauge market size before fetching full datasets.

        Args:
            filters_json: JSON object with filter criteria (same format as search_companies)

        Returns:
            Dict with aggregated statistics:
            - Total count of matching companies
            - Distribution by size, industry, location
            - Other aggregated metrics
            Or error dict if request fails

        Example:
            vibeprospecting_company_statistics(
                filters_json='{"country_code": {"type": "includes", "values": ["us"]}, "industry": {"type": "includes", "values": ["software"]}}'
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            return {"error": "filters_json must be valid JSON"}

        try:
            return client.company_statistics(filters=filters)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def vibeprospecting_autocomplete_company(
        query: str,
        limit: int = 10,
    ) -> dict:
        """
        Autocomplete company search by name or domain.

        Args:
            query: Search query (company name or partial domain)
            limit: Maximum results to return, max 50 (default 10)

        Returns:
            Dict with autocomplete suggestions including:
            - business_id, name, domain
            - Basic company info
            Or error dict if request fails

        Example:
            vibeprospecting_autocomplete_company(query="tesla", limit=5)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not query:
            return {"error": "query is required"}

        try:
            return client.autocomplete_company(query=query, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}