"""
People Data Labs Tool - B2B person and company data enrichment.

Supports:
- API key authentication (PDL_API_KEY)

Use Cases:
- Enrich person profiles by email, phone, LinkedIn, or name
- Search 3 billion+ person profiles with advanced queries
- Identify people from partial information
- Bulk enrichment (up to 100 people at once)
- Enrich and search company data
- Clean and normalize company/location/school names
- Autocomplete for search queries

API Reference: https://docs.peopledatalabs.com/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

PDL_API_BASE = "https://api.peopledatalabs.com/v5"


class _PeopleDataLabsClient:
    """Internal client wrapping People Data Labs API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid People Data Labs API key"}
        if response.status_code == 403:
            return {
                "error": "Insufficient credits or API access denied",
                "help": "Check your PDL plan at https://dashboard.peopledatalabs.com/",
            }
        if response.status_code == 404:
            return {
                "match_found": False,
                "message": "No matching record found",
            }
        if response.status_code == 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid request parameters: {detail}"}
        if response.status_code == 429:
            return {
                "error": "Rate limit exceeded (100/min free, 1000/min paid)",
                "help": "Wait before making more requests or upgrade your plan",
            }
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"PDL API error (HTTP {response.status_code}): {detail}"}

        try:
            return response.json()
        except Exception:
            return {"error": "Invalid JSON response from API"}

    def enrich_person(
        self,
        params: dict[str, Any],
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Enrich a person by various identifiers."""
        query_params = {**params}
        if pretty:
            query_params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/person/enrich",
            headers=self._headers,
            params=query_params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def search_people(
        self,
        query: dict[str, Any],
        size: int = 10,
        scroll_token: str | None = None,
        dataset: str = "all",
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Search people with Elasticsearch-style queries."""
        body: dict[str, Any] = {
            "query": query,
            "size": size,
            "dataset": dataset,
        }
        if scroll_token:
            body["scroll_token"] = scroll_token
        if pretty:
            body["pretty"] = True

        response = httpx.post(
            f"{PDL_API_BASE}/person/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def identify_person(
        self,
        params: dict[str, Any],
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Identify person from partial data with confidence scores."""
        query_params = {**params}
        if pretty:
            query_params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/person/identify",
            headers=self._headers,
            params=query_params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def bulk_enrich_people(
        self,
        requests: list[dict[str, Any]],
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Bulk enrich up to 100 people in a single request."""
        body: dict[str, Any] = {"requests": requests}
        if pretty:
            body["pretty"] = True

        response = httpx.post(
            f"{PDL_API_BASE}/person/bulk",
            headers=self._headers,
            json=body,
            timeout=60.0,
        )
        return self._handle_response(response)

    def enrich_company(
        self,
        params: dict[str, Any],
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Enrich a company by domain, name, or other identifiers."""
        query_params = {**params}
        if pretty:
            query_params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/company/enrich",
            headers=self._headers,
            params=query_params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def search_companies(
        self,
        query: dict[str, Any],
        size: int = 10,
        scroll_token: str | None = None,
        dataset: str = "all",
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Search companies with Elasticsearch-style queries."""
        body: dict[str, Any] = {
            "query": query,
            "size": size,
            "dataset": dataset,
        }
        if scroll_token:
            body["scroll_token"] = scroll_token
        if pretty:
            body["pretty"] = True

        response = httpx.post(
            f"{PDL_API_BASE}/company/search",
            headers=self._headers,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def autocomplete(
        self,
        field: str,
        text: str,
        size: int = 10,
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Get autocomplete suggestions for search queries."""
        params: dict[str, Any] = {
            "field": field,
            "text": text,
            "size": size,
        }
        if pretty:
            params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/autocomplete",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def clean_company(
        self,
        name: str,
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Clean and normalize a company name."""
        params: dict[str, Any] = {"name": name}
        if pretty:
            params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/company/clean",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def clean_location(
        self,
        location: str,
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Clean and normalize a location string."""
        params: dict[str, Any] = {"location": location}
        if pretty:
            params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/location/clean",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def clean_school(
        self,
        name: str,
        pretty: bool = False,
    ) -> dict[str, Any]:
        """Clean and normalize a school name."""
        params: dict[str, Any] = {"name": name}
        if pretty:
            params["pretty"] = "true"

        response = httpx.get(
            f"{PDL_API_BASE}/school/clean",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register People Data Labs enrichment tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get PDL API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("people_data_labs")
            if api_key is not None and not isinstance(api_key, str):
                raise TypeError(
                    f"Expected string from credentials.get('people_data_labs'), got {type(api_key).__name__}"
                )
            return api_key
        return os.getenv("PDL_API_KEY")

    def _get_client() -> _PeopleDataLabsClient | dict[str, str]:
        """Get a PDL client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "People Data Labs credentials not configured",
                "help": (
                    "Set PDL_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get your API key at https://dashboard.peopledatalabs.com/"
                ),
            }
        return _PeopleDataLabsClient(api_key)

    # --- Person Enrichment ---

    @mcp.tool()
    def pdl_enrich_person(
        email: str | None = None,
        phone: str | None = None,
        profile: str | None = None,
        lid: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        name: str | None = None,
        company: str | None = None,
        location: str | None = None,
        locality: str | None = None,
        region: str | None = None,
        school: str | None = None,
        pretty: bool = False,
    ) -> dict:
        """
        Enrich a person profile from 3 billion+ records.

        Minimum required combinations:
        - email OR phone OR profile OR lid
        - OR (first_name AND last_name) AND (company OR location OR locality OR region OR school)

        Args:
            email: Email address
            phone: Phone number (E.164 format recommended)
            profile: Social profile URL (LinkedIn, Facebook, Twitter, etc.)
            lid: LinkedIn numeric ID
            first_name: First name
            last_name: Last name
            name: Full name (alternative to first_name + last_name)
            company: Company name or domain
            location: Full location string
            locality: City name
            region: State/province
            school: School/university name
            pretty: Format JSON response (default: False)

        Returns:
            Dict with enriched person data including:
            - Full name, emails, phone numbers
            - Current job (title, company, seniority, start date)
            - Work history and education
            - Skills, interests, certifications
            - Social profiles (LinkedIn, Twitter, Facebook, GitHub)
            - Location details
            Or match_found: False if no match

        Example:
            pdl_enrich_person(email="[email protected]")
            pdl_enrich_person(first_name="Sean", last_name="Thorne", company="People Data Labs")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if profile:
            params["profile"] = profile
        if lid:
            params["lid"] = lid
        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if name:
            params["name"] = name
        if company:
            params["company"] = company
        if location:
            params["location"] = location
        if locality:
            params["locality"] = locality
        if region:
            params["region"] = region
        if school:
            params["school"] = school

        if not params:
            return {
                "error": "Must provide at least one search parameter",
                "help": "Minimum: email, phone, profile, lid, or (name + company/location)",
            }

        try:
            return client.enrich_person(params, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Person Search ---

    @mcp.tool()
    def pdl_search_people(
        query_json: str,
        size: int = 10,
        scroll_token: str | None = None,
        dataset: str = "all",
        pretty: bool = False,
    ) -> dict:
        """
        Search 3 billion+ person profiles with Elasticsearch-style queries.

        Args:
            query_json: Elasticsearch JSON query (ES DSL format). Examples:
                Simple: '{"term": {"job_company_name": "google"}}'
                Combined: '{"bool": {"must": [
                    {"term": {"job_title_role": "sales"}},
                    {"term": {"location_country": "united states"}}
                ]}}'
            size: Number of results (1-100, default 10)
            scroll_token: Pagination token from previous response
            dataset: Dataset to search ("all", "phone", "mobile_phone")
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - total: Total matching records
            - data: List of person records
            - scroll_token: Token for next page (if more results)

        Common query fields:
            - job_title_role, job_title_sub_role, job_title_levels
            - job_company_name, job_company_website, job_company_industry
            - location_country, location_region, location_locality
            - education_school_name, education_degrees
            - skills, languages, interests
            - experience (person, company, title, school)

        Example:
            pdl_search_people(
                query_json='{"bool": {"must": [
                    {"term": {"job_title_role": "sales"}},
                    {"term": {"job_company_size": "1001-5000"}},
                    {"term": {"location_country": "united states"}}
                ]}}',
                size=25
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            query = json.loads(query_json)
        except json.JSONDecodeError:
            return {"error": "query_json must be valid JSON"}

        try:
            return client.search_people(
                query=query,
                size=size,
                scroll_token=scroll_token,
                dataset=dataset,
                pretty=pretty,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Person Identify ---

    @mcp.tool()
    def pdl_identify_person(
        email: str | None = None,
        phone: str | None = None,
        profile: str | None = None,
        name: str | None = None,
        company: str | None = None,
        location: str | None = None,
        pretty: bool = False,
    ) -> dict:
        """
        Identify multiple possible matches for a person with confidence scores.

        Unlike enrich (which returns best match), identify returns ALL potential
        matches ranked by likelihood, useful when you have partial information.

        Args:
            email: Email address
            phone: Phone number
            profile: Social profile URL
            name: Full name
            company: Company name
            location: Location string
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - total: Number of potential matches
            - matches: List of possible person records with likelihood scores
            Each match includes full person data + likelihood (0-10 scale)

        Example:
            pdl_identify_person(name="John Smith", company="Google", location="California")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if profile:
            params["profile"] = profile
        if name:
            params["name"] = name
        if company:
            params["company"] = company
        if location:
            params["location"] = location

        if not params:
            return {"error": "Must provide at least one search parameter"}

        try:
            return client.identify_person(params, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Bulk Person Enrichment ---

    @mcp.tool()
    def pdl_bulk_enrich_people(
        requests_json: str,
        pretty: bool = False,
    ) -> dict:
        """
        Bulk enrich up to 100 people in a single request.

        Args:
            requests_json: JSON array of enrichment requests. Each request is an object
                with the same parameters as pdl_enrich_person.
                Example: '[
                    {"params": {"email": "[email protected]"}},
                    {"params": {"first_name": "Jane", "last_name": "Doe", "company": "Acme"}}
                ]'
            pretty: Format JSON response (default: False)

        Returns:
            Dict with array of results, one per input request.
            Each result contains either person data or error.

        Example:
            pdl_bulk_enrich_people(
                requests_json='[
                    {"params": {"email": "[email protected]"}},
                    {"params": {"email": "[email protected]"}}
                ]'
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            requests = json.loads(requests_json)
        except json.JSONDecodeError:
            return {"error": "requests_json must be valid JSON"}

        if not isinstance(requests, list) or len(requests) == 0:
            return {"error": "requests_json must be a non-empty JSON array"}
        if len(requests) > 100:
            return {"error": "maximum 100 requests per bulk operation"}

        try:
            return client.bulk_enrich_people(requests, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Company Enrichment ---

    @mcp.tool()
    def pdl_enrich_company(
        website: str | None = None,
        name: str | None = None,
        profile: str | None = None,
        ticker: str | None = None,
        location: str | None = None,
        locality: str | None = None,
        region: str | None = None,
        pretty: bool = False,
    ) -> dict:
        """
        Enrich company data by domain, name, or other identifiers.

        Args:
            website: Company website/domain (e.g., "google.com")
            name: Company name
            profile: LinkedIn company profile URL
            ticker: Stock ticker symbol
            location: Full location string
            locality: City
            region: State/province
            pretty: Format JSON response (default: False)

        Returns:
            Dict with enriched company data including:
            - Name, domain, description
            - Industry, size, founded year
            - Location and headquarters
            - LinkedIn URL, Twitter, Facebook
            - Employee count, revenue estimates
            - Technologies used
            Or match_found: False if no match

        Example:
            pdl_enrich_company(website="peopledatalabs.com")
            pdl_enrich_company(name="Google", locality="Mountain View")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        params: dict[str, Any] = {}
        if website:
            params["website"] = website
        if name:
            params["name"] = name
        if profile:
            params["profile"] = profile
        if ticker:
            params["ticker"] = ticker
        if location:
            params["location"] = location
        if locality:
            params["locality"] = locality
        if region:
            params["region"] = region

        if not params:
            return {"error": "Must provide at least one search parameter"}

        try:
            return client.enrich_company(params, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Company Search ---

    @mcp.tool()
    def pdl_search_companies(
        query_json: str,
        size: int = 10,
        scroll_token: str | None = None,
        dataset: str = "all",
        pretty: bool = False,
    ) -> dict:
        """
        Search companies with Elasticsearch-style queries.

        Args:
            query_json: Elasticsearch JSON query. Examples:
                Simple: '{"term": {"industry": "computer software"}}'
                Range: '{"range": {"size": {"gte": 100, "lte": 1000}}}'
                Combined: '{"bool": {"must": [
                    {"term": {"industry": "technology"}},
                    {"term": {"location.country": "united states"}}
                ]}}'
            size: Number of results (1-100, default 10)
            scroll_token: Pagination token from previous response
            dataset: Dataset to search (default: "all")
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - total: Total matching companies
            - data: List of company records
            - scroll_token: Token for next page

        Common query fields:
            - name, website, industry, tags
            - size (employee count), founded
            - location.country, location.region, location.locality
            - linkedin_url, twitter_url, facebook_url

        Example:
            pdl_search_companies(
                query_json='{"bool": {"must": [
                    {"term": {"industry": "computer software"}},
                    {"range": {"size": {"gte": 50, "lte": 500}}}
                ]}}',
                size=20
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        import json

        try:
            query = json.loads(query_json)
        except json.JSONDecodeError:
            return {"error": "query_json must be valid JSON"}

        try:
            return client.search_companies(
                query=query,
                size=size,
                scroll_token=scroll_token,
                dataset=dataset,
                pretty=pretty,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Autocomplete ---

    @mcp.tool()
    def pdl_autocomplete(
        field: str,
        text: str,
        size: int = 10,
        pretty: bool = False,
    ) -> dict:
        """
        Get autocomplete suggestions for search query fields.

        Useful for building search UIs or validating input values.

        Args:
            field: Field name to autocomplete. Options:
                - company, school, title, skill, country, region, city, industry
            text: Partial text to autocomplete (e.g., "stanf" → "Stanford University")
            size: Number of suggestions (1-100, default 10)
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - data: List of suggestions with text and count
            Each suggestion includes the full text and number of matching records

        Example:
            pdl_autocomplete(field="school", text="stanf", size=5)
            pdl_autocomplete(field="title", text="software eng", size=10)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        valid_fields = ["company", "school", "title", "skill", "country", "region", "city", "industry"]
        if field not in valid_fields:
            return {
                "error": f"Invalid field. Must be one of: {', '.join(valid_fields)}"
            }

        if not text:
            return {"error": "text parameter is required"}

        try:
            return client.autocomplete(field=field, text=text, size=size, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Cleaner APIs ---

    @mcp.tool()
    def pdl_clean_company(
        name: str,
        pretty: bool = False,
    ) -> dict:
        """
        Clean and normalize a company name for better matching.

        Removes common suffixes (Inc, LLC, Ltd), standardizes formatting,
        and returns canonical company name.

        Args:
            name: Raw company name (e.g., "peOple DaTa LabS, inc.")
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - name: Cleaned company name (e.g., "people data labs")

        Example:
            pdl_clean_company(name="Google, Inc.")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not name:
            return {"error": "name parameter is required"}

        try:
            return client.clean_company(name=name, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def pdl_clean_location(
        location: str,
        pretty: bool = False,
    ) -> dict:
        """
        Clean and normalize a location string.

        Parses free-form location text into structured components
        (country, region, locality, etc.) for better matching.

        Args:
            location: Raw location string (e.g., "san fran, ca, usa")
            pretty: Format JSON response (default: False)

        Returns:
            Dict with parsed location components:
            - name: Full standardized location name
            - locality: City name
            - region: State/province
            - country: Country name
            - continent: Continent
            - lat/lon: Coordinates (if available)

        Example:
            pdl_clean_location(location="NYC, NY")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not location:
            return {"error": "location parameter is required"}

        try:
            return client.clean_location(location=location, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def pdl_clean_school(
        name: str,
        pretty: bool = False,
    ) -> dict:
        """
        Clean and normalize a school/university name.

        Standardizes school names for better matching across datasets.

        Args:
            name: Raw school name (e.g., "university of oregon")
            pretty: Format JSON response (default: False)

        Returns:
            Dict with:
            - name: Cleaned school name (e.g., "university of oregon")

        Example:
            pdl_clean_school(name="MIT")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not name:
            return {"error": "name parameter is required"}

        try:
            return client.clean_school(name=name, pretty=pretty)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}