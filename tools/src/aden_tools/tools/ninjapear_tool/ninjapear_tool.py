"""
NinjaPear Tool - Company and people enrichment via the NinjaPear API.

Supports:
- Person/employee profile lookup (by work email, name+employer, or employer+role)
- Company details, funding, updates, customers, and competitors
- Credit balance check (free endpoint)

API Reference: https://nubela.co/docs/
Auth: Authorization: Bearer {api_key}
Note: API response times are 30-60s; client timeout is set to 100s.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

NINJAPEAR_API_BASE = "https://nubela.co"


class _NinjaPearClient:
    """Internal client wrapping NinjaPear API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Map HTTP status codes to user-friendly errors."""
        if response.status_code == 401:
            return {"error": "Invalid NinjaPear API key"}
        if response.status_code == 403:
            return {"error": "NinjaPear: out of credits or insufficient permissions"}
        if response.status_code == 404:
            try:
                detail = response.json()
                msg = detail.get("message") or detail.get("error") or str(detail)
            except Exception:
                msg = response.text or "no data found"
            return {"error": f"Not found: {msg}"}
        if response.status_code == 410:
            return {"error": "NinjaPear: this API endpoint has been deprecated"}
        if response.status_code == 429:
            return {
                "error": "NinjaPear rate limit exceeded. Trial accounts are limited to "
                "2 requests/minute. Apply exponential backoff and retry."
            }
        if response.status_code == 503:
            return {
                "error": "NinjaPear enrichment failed (503). The service is temporarily "
                "unavailable. Retry the request — no credits were charged."
            }
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"NinjaPear API error (HTTP {response.status_code}): {detail}"}
        try:
            return response.json()
        except Exception:
            return {"error": f"Failed to parse NinjaPear response: {response.text[:500]}"}

    def get_person_profile(
        self,
        work_email: str = "",
        first_name: str = "",
        last_name: str = "",
        middle_name: str = "",
        employer_website: str = "",
        role: str = "",
        slug: str = "",
        profile_id: str = "",
    ) -> dict[str, Any]:
        """Look up a person's professional profile."""
        params: dict[str, str] = {}
        if work_email:
            params["work_email"] = work_email
        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if middle_name:
            params["middle_name"] = middle_name
        if employer_website:
            params["employer_website"] = employer_website
        if role:
            params["role"] = role
        if slug:
            params["slug"] = slug
        if profile_id:
            params["id"] = profile_id

        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/employee/profile",
            headers=self._headers,
            params=params,
            # API docs warn 30-60s response times; use 100s as recommended
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_company_details(
        self,
        website: str,
        include_employee_count: bool = False,
        include_follower_count: bool = False,
    ) -> dict[str, Any]:
        """Get full company metadata."""
        params: dict[str, str] = {"website": website}
        if include_employee_count:
            params["include_employee_count"] = "true"
        if include_follower_count:
            params["follower_count"] = "include"

        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/company/details",
            headers=self._headers,
            params=params,
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_company_funding(self, website: str) -> dict[str, Any]:
        """Get full funding history for a company."""
        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/company/funding",
            headers=self._headers,
            params={"website": website},
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_company_updates(self, website: str) -> dict[str, Any]:
        """Get latest blog posts and X/Twitter updates for a company."""
        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/company/updates",
            headers=self._headers,
            params={"website": website},
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_company_customers(
        self,
        website: str,
        cursor: str = "",
        page_size: int = 200,
        quality_filter: bool = True,
    ) -> dict[str, Any]:
        """Get customers, investors, and partner companies for a target company."""
        params: dict[str, Any] = {
            "website": website,
            "page_size": page_size,
        }
        if cursor:
            params["cursor"] = cursor
        if not quality_filter:
            params["quality_filter"] = "false"

        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/customer/listing",
            headers=self._headers,
            params=params,
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_company_competitors(self, website: str) -> dict[str, Any]:
        """Get competitor companies for a target company."""
        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/competitor/listing",
            headers=self._headers,
            params={"website": website},
            timeout=100.0,
        )
        return self._handle_response(response)

    def get_credit_balance(self) -> dict[str, Any]:
        """Get remaining credit balance (free endpoint, 0 credits)."""
        response = httpx.get(
            f"{NINJAPEAR_API_BASE}/api/v1/meta/credit-balance",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register NinjaPear enrichment tools with the MCP server."""

    def _get_api_key(account: str = "") -> str | None:
        """Get NinjaPear API key from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("ninjapear", account)
            key = credentials.get("ninjapear")
            if key is not None and not isinstance(key, str):
                raise TypeError(
                    f"Expected string from credentials.get('ninjapear'), got {type(key).__name__}"
                )
            return key
        return os.getenv("NINJAPEAR_API_KEY")

    def _get_client(account: str = "") -> _NinjaPearClient | dict[str, str]:
        """Get a NinjaPear client, or return an error dict if no credentials."""
        key = _get_api_key(account)
        if not key:
            return {
                "error": "NinjaPear credentials not configured",
                "help": (
                    "Set the NINJAPEAR_API_KEY environment variable "
                    "or configure via credential store"
                ),
            }
        return _NinjaPearClient(key)

    # --- Person ---

    @mcp.tool()
    def ninjapear_get_person_profile(
        work_email: str = "",
        first_name: str = "",
        last_name: str = "",
        middle_name: str = "",
        employer_website: str = "",
        role: str = "",
        slug: str = "",
        profile_id: str = "",
        account: str = "",
    ) -> dict:
        """
        Look up a person's professional profile via NinjaPear enrichment.

        You must provide one of the following valid input combinations:
        - work_email alone
        - first_name + employer_website (last_name and role improve accuracy)
        - employer_website + role (returns the person currently holding that role)
        - slug alone (e.g. their X/Twitter handle — free on 404)
        - profile_id alone (NinjaPear internal ID — free on 404)

        Returns profile data including work experience, education, location,
        X/Twitter handle, and bio. Note: 3 credits are consumed per successful
        lookup. Trial accounts are limited to 2 requests/minute.

        Args:
            work_email: Work email address of the person
            first_name: First name (use with employer_website)
            last_name: Last name (improves accuracy when used with first_name)
            middle_name: Middle name (improves accuracy)
            employer_website: Employer's website URL (e.g. "stripe.com")
            role: Job title or role (e.g. "CTO", "Head of Engineering")
            slug: NinjaPear slug (usually the person's X/Twitter handle)
            profile_id: NinjaPear internal 8-character profile ID
            account: Account alias for multi-account support

        Returns:
            Dict with profile data (id, slug, full_name, work_experience,
            education, location, x_handle, bio, follower_count) or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client

        # Validate that at least one meaningful input was provided
        has_email = bool(work_email)
        has_name_employer = bool(first_name and employer_website)
        has_role_employer = bool(role and employer_website)
        has_slug = bool(slug)
        has_id = bool(profile_id)

        if not any([has_email, has_name_employer, has_role_employer, has_slug, has_id]):
            return {
                "error": (
                    "Insufficient input. Provide one of: "
                    "(1) work_email, "
                    "(2) first_name + employer_website, "
                    "(3) employer_website + role, "
                    "(4) slug, "
                    "(5) profile_id"
                )
            }

        try:
            return client.get_person_profile(
                work_email=work_email,
                first_name=first_name,
                last_name=last_name,
                middle_name=middle_name,
                employer_website=employer_website,
                role=role,
                slug=slug,
                profile_id=profile_id,
            )
        except httpx.TimeoutException:
            return {
                "error": (
                    "Request timed out after 100s. NinjaPear enrichment can take 30-60s. "
                    "Retry the request."
                )
            }
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Company ---

    @mcp.tool()
    def ninjapear_get_company_details(
        website: str,
        include_employee_count: bool = False,
        include_follower_count: bool = False,
        account: str = "",
    ) -> dict:
        """
        Get detailed metadata for a company via NinjaPear.

        Returns company description, industry (GICS), type, founding year,
        specialties, addresses, executives, social links, and optionally
        employee count and follower counts.

        Credit cost: 2 credits base + 2 if include_employee_count=True
        + 1 if include_follower_count=True. Charged even when no data found.

        Args:
            website: Company website URL (e.g. "stripe.com")
            include_employee_count: If True, include estimated headcount (+2 credits)
            include_follower_count: If True, include X/Twitter follower count (+1 credit)
            account: Account alias for multi-account support

        Returns:
            Dict with company metadata or error
        """
        if not website:
            return {"error": "website is required"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_company_details(
                website, include_employee_count, include_follower_count
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out after 100s. Retry the request."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ninjapear_get_company_funding(
        website: str,
        account: str = "",
    ) -> dict:
        """
        Get the full funding history for a company via NinjaPear.

        Returns total funds raised and a list of funding rounds with date,
        round type, amount, and investors.

        Round types include: PRE_SEED, SEED, SERIES_A through SERIES_Z,
        BRIDGE, VENTURE_DEBT, CONVERTIBLE_NOTE, GRANT, IPO, and more.

        Credit cost: 2 credits base + 1 credit per unique investor returned.
        Base cost charged even on 404.

        Args:
            website: Company website URL (e.g. "stripe.com")
            account: Account alias for multi-account support

        Returns:
            Dict with total_funds_raised_usd and funding_rounds list, or error
        """
        if not website:
            return {"error": "website is required"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_company_funding(website)
        except httpx.TimeoutException:
            return {"error": "Request timed out after 100s. Retry the request."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ninjapear_get_company_updates(
        website: str,
        account: str = "",
    ) -> dict:
        """
        Get the latest blog posts and X/Twitter updates for a company via NinjaPear.

        Returns recent updates sorted by timestamp (newest first). Useful for
        identifying hiring signals, product launches, and company news.

        Credit cost: 2 credits per request.

        Args:
            website: Company website URL (e.g. "stripe.com")
            account: Account alias for multi-account support

        Returns:
            Dict with updates list (url, title, description, timestamp, source)
            and blogs list, or error
        """
        if not website:
            return {"error": "website is required"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_company_updates(website)
        except httpx.TimeoutException:
            return {"error": "Request timed out after 100s. Retry the request."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ninjapear_get_company_customers(
        website: str,
        cursor: str = "",
        page_size: int = 50,
        quality_filter: bool = True,
        account: str = "",
    ) -> dict:
        """
        Get customers, investors, and partner companies of a target company via NinjaPear.

        Useful for understanding who uses a product (social proof) and for
        expanding a sourcing universe to adjacent companies.

        Credit cost: 1 credit + 2 credits per company returned. Charged even on
        empty results.

        Args:
            website: Target company website URL (e.g. "stripe.com")
            cursor: Pagination cursor from a previous response's next_page field
            page_size: Number of results per page (1-200, default 50)
            quality_filter: If True (default), filter out low-quality results
            account: Account alias for multi-account support

        Returns:
            Dict with customers, investors, partner_platforms lists and
            next_page cursor, or error
        """
        if not website:
            return {"error": "website is required"}
        if not 1 <= page_size <= 200:
            return {"error": "page_size must be between 1 and 200"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_company_customers(website, cursor, page_size, quality_filter)
        except httpx.TimeoutException:
            return {"error": "Request timed out after 100s. Retry the request."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def ninjapear_get_company_competitors(
        website: str,
        account: str = "",
    ) -> dict:
        """
        Get competitor companies for a target company via NinjaPear.

        Returns a list of competitors with their website and the reason for
        competition (organic_keyword_overlap or product_overlap).

        Useful for expanding a sourcing universe — e.g. find all companies
        competing with a known target and source candidates from each.

        Credit cost: 2 credits per competitor returned. Minimum 5 credits
        per request, charged even on empty results.

        Args:
            website: Target company website URL (e.g. "stripe.com")
            account: Account alias for multi-account support

        Returns:
            Dict with competitors list (website, company_details_url,
            competition_reason), or error
        """
        if not website:
            return {"error": "website is required"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_company_competitors(website)
        except httpx.TimeoutException:
            return {"error": "Request timed out after 100s. Retry the request."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Meta ---

    @mcp.tool()
    def ninjapear_get_credit_balance(account: str = "") -> dict:
        """
        Get the remaining NinjaPear credit balance.

        This is a free endpoint (0 credits consumed). Use it to check available
        budget before running credit-intensive workflows.

        Args:
            account: Account alias for multi-account support

        Returns:
            Dict with credit_balance (int), or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_credit_balance()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
