"""Lusha API integration.

Provides B2B contact enrichment and company data via the Lusha REST API.
Requires LUSHA_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.lusha.com"


def _get_headers() -> dict | None:
    """Return headers dict or None if key missing."""
    api_key = os.getenv("LUSHA_API_KEY", "")
    if not api_key:
        return None
    return {"api_key": api_key, "Content-Type": "application/json"}


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, headers: dict, payload: dict) -> dict:
    """Send a POST request."""
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_person(p: dict) -> dict:
    """Extract key person fields."""
    return {
        "first_name": p.get("firstName"),
        "last_name": p.get("lastName"),
        "full_name": p.get("fullName"),
        "job_title": p.get("jobTitle"),
        "company": p.get("company"),
        "email_addresses": p.get("emailAddresses", []),
        "phone_numbers": p.get("phoneNumbers", []),
        "linkedin_url": p.get("linkedinUrl"),
        "location": p.get("location"),
    }


def _extract_company(c: dict) -> dict:
    """Extract key company fields."""
    return {
        "name": c.get("name") or c.get("companyName"),
        "domain": c.get("domain") or c.get("companyDomain"),
        "industry": c.get("industry"),
        "employee_count": c.get("employeeCount"),
        "revenue": c.get("revenue"),
        "location": c.get("location"),
        "description": c.get("description"),
        "founded_year": c.get("foundedYear"),
        "technologies": c.get("technologies", []),
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Lusha tools."""

    @mcp.tool()
    def lusha_enrich_person(
        first_name: str = "",
        last_name: str = "",
        company_domain: str = "",
        email: str = "",
        linkedin_url: str = "",
    ) -> dict:
        """Enrich a person/contact with Lusha data (emails, phones, job info).

        Args:
            first_name: Person's first name (use with last_name + company_domain).
            last_name: Person's last name.
            company_domain: Company domain (e.g. 'acme.com').
            email: Person's email address (alternative to name+company).
            linkedin_url: Person's LinkedIn profile URL (alternative lookup).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        params: dict[str, str] = {}
        if email:
            params["email"] = email
        elif linkedin_url:
            params["linkedinUrl"] = linkedin_url
        elif first_name and last_name:
            params["firstName"] = first_name
            params["lastName"] = last_name
            if company_domain:
                params["companyDomain"] = company_domain
        else:
            return {"error": "Provide email, linkedinUrl, or firstName+lastName"}

        data = _get(f"{BASE_URL}/v2/person", headers, params)
        if "error" in data:
            return data

        return _extract_person(data)

    @mcp.tool()
    def lusha_enrich_company(
        domain: str = "",
        company_name: str = "",
    ) -> dict:
        """Enrich a company with Lusha firmographic data.

        Args:
            domain: Company domain (e.g. 'acme.com').
            company_name: Company name (alternative to domain).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        params: dict[str, str] = {}
        if domain:
            params["domain"] = domain
        elif company_name:
            params["companyName"] = company_name
        else:
            return {"error": "Provide domain or companyName"}

        data = _get(f"{BASE_URL}/v2/company", headers, params)
        if "error" in data:
            return data

        return _extract_company(data)

    @mcp.tool()
    def lusha_search_contacts(
        seniorities: str = "",
        departments: str = "",
        company_names: str = "",
        company_domains: str = "",
        country: str = "",
        page: int = 0,
        page_size: int = 20,
    ) -> dict:
        """Search for B2B contacts using Lusha prospecting filters.

        Args:
            seniorities: Comma-separated seniority levels (e.g. '4,5' for VP/C-level).
            departments: Comma-separated departments (e.g. 'Engineering & Technical,Marketing').
            company_names: Comma-separated company names to filter by.
            company_domains: Comma-separated company domains to filter by.
            country: Country name to filter by.
            page: Page number (0-indexed, default 0).
            page_size: Results per page (default 20).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        contacts_include: dict[str, Any] = {}
        companies_include: dict[str, Any] = {}

        if seniorities:
            contacts_include["seniorities"] = [s.strip() for s in seniorities.split(",")]
        if departments:
            contacts_include["departments"] = [d.strip() for d in departments.split(",")]
        if country:
            contacts_include["locations"] = [{"country": country}]
        if company_names:
            companies_include["names"] = [n.strip() for n in company_names.split(",")]
        if company_domains:
            companies_include["domains"] = [d.strip() for d in company_domains.split(",")]

        if not contacts_include and not companies_include:
            return {"error": "At least one filter is required"}

        payload: dict[str, Any] = {
            "pages": {"page": page, "size": min(page_size, 100)},
        }
        filters: dict[str, Any] = {}
        if contacts_include:
            filters["contacts"] = {"include": contacts_include}
        if companies_include:
            filters["companies"] = {"include": companies_include}
        payload["filters"] = filters

        data = _post(f"{BASE_URL}/prospecting/contact/search", headers, payload)
        if "error" in data:
            return data

        contacts = data.get("data", [])
        return {
            "count": len(contacts),
            "total": data.get("total"),
            "contacts": [
                {
                    "id": c.get("contactId"),
                    "first_name": c.get("firstName"),
                    "last_name": c.get("lastName"),
                    "job_title": c.get("jobTitle"),
                    "seniority": c.get("seniority"),
                    "department": c.get("department"),
                    "company_name": c.get("companyName"),
                    "company_domain": c.get("companyDomain"),
                    "location": c.get("location"),
                }
                for c in contacts
            ],
        }

    @mcp.tool()
    def lusha_search_companies(
        company_names: str = "",
        domains: str = "",
        country: str = "",
        min_employees: int = 0,
        max_employees: int = 0,
        page: int = 0,
        page_size: int = 20,
    ) -> dict:
        """Search for companies using Lusha prospecting filters.

        Args:
            company_names: Comma-separated company names.
            domains: Comma-separated domains.
            country: Country name to filter by.
            min_employees: Minimum employee count.
            max_employees: Maximum employee count.
            page: Page number (0-indexed, default 0).
            page_size: Results per page (default 20).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        companies_include: dict[str, Any] = {}
        if company_names:
            companies_include["names"] = [n.strip() for n in company_names.split(",")]
        if domains:
            companies_include["domains"] = [d.strip() for d in domains.split(",")]
        if country:
            companies_include["locations"] = [{"country": country}]
        if min_employees > 0 or max_employees > 0:
            size_filter: dict[str, int] = {}
            if min_employees > 0:
                size_filter["min"] = min_employees
            if max_employees > 0:
                size_filter["max"] = max_employees
            companies_include["sizes"] = [size_filter]

        if not companies_include:
            return {"error": "At least one filter is required"}

        payload: dict[str, Any] = {
            "pages": {"page": page, "size": min(page_size, 100)},
            "filters": {"companies": {"include": companies_include}},
        }

        data = _post(f"{BASE_URL}/prospecting/company/search", headers, payload)
        if "error" in data:
            return data

        companies = data.get("data", [])
        return {
            "count": len(companies),
            "total": data.get("total"),
            "companies": [_extract_company(c) for c in companies],
        }

    @mcp.tool()
    def lusha_get_usage() -> dict:
        """Get Lusha API credit usage statistics."""
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        data = _get(f"{BASE_URL}/account/usage", headers)
        if "error" in data:
            return data

        return data

    @mcp.tool()
    def lusha_bulk_enrich_persons(
        details_json: str,
    ) -> dict:
        """Bulk enrich multiple persons in a single request.

        Args:
            details_json: JSON array of person objects. Each object should have
                at least one of: email, linkedinUrl, or firstName+lastName+companyDomain.
                Example: [{"email": "j@acme.com"},
                {"firstName": "Jane", "lastName": "Doe", "companyDomain": "acme.com"}]
        """
        import json as _json

        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }

        try:
            persons = _json.loads(details_json)
        except _json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}"}

        if not isinstance(persons, list) or not persons:
            return {"error": "details_json must be a non-empty JSON array"}
        if len(persons) > 50:
            return {"error": "Maximum 50 persons per request"}

        payload = {"contacts": persons}
        data = _post(f"{BASE_URL}/v2/person/bulk", headers, payload)
        if "error" in data:
            return data

        results = []
        for p in data.get("data", data.get("contacts", [])):
            results.append(_extract_person(p))
        return {"results": results, "count": len(results)}

    @mcp.tool()
    def lusha_get_technologies(
        domain: str,
    ) -> dict:
        """Get the technology stack used by a company.

        Args:
            domain: Company domain (e.g. 'acme.com').
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }
        if not domain:
            return {"error": "domain is required"}

        data = _get(f"{BASE_URL}/v2/company", headers, {"domain": domain})
        if "error" in data:
            return data

        return {
            "domain": domain,
            "company_name": data.get("name") or data.get("companyName", ""),
            "technologies": data.get("technologies", []),
            "industry": data.get("industry", ""),
        }

    @mcp.tool()
    def lusha_search_decision_makers(
        company_domains: str,
        country: str = "",
        page: int = 0,
        page_size: int = 20,
    ) -> dict:
        """Search for decision makers (VP, C-level, Director) at companies.

        Convenience wrapper around lusha_search_contacts pre-filtered for
        senior seniority levels (Director, VP, C-level, Owner/Partner).

        Args:
            company_domains: Comma-separated company domains (e.g. 'acme.com,example.com').
            country: Country name to filter by (optional).
            page: Page number (0-indexed, default 0).
            page_size: Results per page (default 20).
        """
        headers = _get_headers()
        if not headers:
            return {
                "error": "LUSHA_API_KEY is required",
                "help": "Set LUSHA_API_KEY environment variable",
            }
        if not company_domains:
            return {"error": "company_domains is required"}

        contacts_include: dict[str, Any] = {
            # Seniority levels: 4=Director, 5=VP, 6=C-level, 7=Owner/Partner
            "seniorities": ["4", "5", "6", "7"],
        }
        if country:
            contacts_include["locations"] = [{"country": country}]

        companies_include: dict[str, Any] = {
            "domains": [d.strip() for d in company_domains.split(",")],
        }

        payload: dict[str, Any] = {
            "pages": {"page": page, "size": min(page_size, 100)},
            "filters": {
                "contacts": {"include": contacts_include},
                "companies": {"include": companies_include},
            },
        }

        data = _post(f"{BASE_URL}/prospecting/contact/search", headers, payload)
        if "error" in data:
            return data

        contacts = data.get("data", [])
        return {
            "count": len(contacts),
            "total": data.get("total"),
            "contacts": [
                {
                    "id": c.get("contactId"),
                    "first_name": c.get("firstName"),
                    "last_name": c.get("lastName"),
                    "job_title": c.get("jobTitle"),
                    "seniority": c.get("seniority"),
                    "department": c.get("department"),
                    "company_name": c.get("companyName"),
                    "company_domain": c.get("companyDomain"),
                    "location": c.get("location"),
                }
                for c in contacts
            ],
        }
