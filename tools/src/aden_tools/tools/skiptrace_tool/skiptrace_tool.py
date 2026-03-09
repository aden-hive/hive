"""
Skip Trace Tool - Mailing address lookup for business contacts.

Supports:
- API key authentication (SKIPTRACE_API_KEY)
- Business address lookup by name and company
- CSV batch processing fallback

Use Cases:
- Direct mail campaigns
- Address verification for outreach
- Enriching contact records with mailing addresses

Note: This tool uses third-party skip tracing services.
Ensure compliance with applicable laws and regulations.
"""

from __future__ import annotations

import csv
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

SKIPTRACE_API_BASE = "https://api.skiptrace.io/v1"


class _SkipTraceClient:
    """Internal client wrapping Skip Trace API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Skip Trace API key"}
        if response.status_code == 402:
            return {"error": "Insufficient credits. Check your Skip Trace balance."}
        if response.status_code == 404:
            return {"error": "No address found for the provided information"}
        if response.status_code == 422:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid parameters: {detail}"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Skip Trace API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def lookup_address(
        self,
        first_name: str,
        last_name: str,
        company: str | None = None,
        domain: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Look up mailing address for a contact."""
        payload = {
            "first_name": first_name,
            "last_name": last_name,
        }

        if company:
            payload["company"] = company
        if domain:
            payload["domain"] = domain
        if state:
            payload["state"] = state

        response = httpx.post(
            f"{SKIPTRACE_API_BASE}/lookup",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            addresses = result.get("addresses", [])
            if addresses:
                best_match = addresses[0]
                return {
                    "found": True,
                    "address": {
                        "street": best_match.get("street"),
                        "city": best_match.get("city"),
                        "state": best_match.get("state"),
                        "zip": best_match.get("postal_code"),
                        "country": best_match.get("country", "USA"),
                    },
                    "confidence": best_match.get("confidence", "medium"),
                    "address_type": best_match.get("type", "business"),
                }
            return {"found": False, "message": "No addresses found for this contact"}
        return result

    def batch_lookup(
        self,
        contacts: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Batch lookup addresses for multiple contacts."""
        payload = {"contacts": contacts}

        response = httpx.post(
            f"{SKIPTRACE_API_BASE}/batch",
            headers=self._headers,
            json=payload,
            timeout=60.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "total": len(contacts),
                "found": result.get("found_count", 0),
                "results": result.get("results", []),
            }
        return result


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Skip Trace tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Skip Trace API key from credentials or environment."""
        if credentials is not None:
            return credentials.get("skiptrace")
        return os.getenv("SKIPTRACE_API_KEY")

    def _get_client() -> _SkipTraceClient | dict[str, str]:
        """Get a Skip Trace client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Skip Trace credentials not configured",
                "help": (
                    "Set SKIPTRACE_API_KEY environment variable "
                    "or configure via credential store. "
                    "Sign up at https://skiptrace.io for API access."
                ),
            }
        return _SkipTraceClient(api_key)

    @mcp.tool()
    def skiptrace_lookup(
        first_name: str,
        last_name: str,
        company: str | None = None,
        domain: str | None = None,
        state: str | None = None,
    ) -> dict:
        """
        Look up a mailing address for a business contact.

        Args:
            first_name: Contact's first name
            last_name: Contact's last name
            company: Company name (improves accuracy)
            domain: Company website domain (e.g., "acme.com")
            state: State code to narrow search (e.g., "CA")

        Returns:
            Dict with:
            - found: Boolean indicating if address was found
            - address: Mailing address details (if found)
                - street: Street address
                - city: City
                - state: State/province
                - zip: Postal/ZIP code
                - country: Country code
            - confidence: Match confidence ("high", "medium", "low")
            - address_type: "business" or "residential"

        Example:
            skiptrace_lookup(
                first_name="John",
                last_name="Doe",
                company="Acme Corp",
                domain="acme.com"
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not first_name or not last_name:
            return {"error": "First name and last name are required"}

        try:
            return client.lookup_address(
                first_name=first_name,
                last_name=last_name,
                company=company,
                domain=domain,
                state=state,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def skiptrace_batch_lookup(
        contacts: list[dict[str, str]],
    ) -> dict:
        """
        Look up mailing addresses for multiple contacts in batch.

        Args:
            contacts: List of contact dicts, each with:
                - first_name: Required
                - last_name: Required
                - company: Optional, improves accuracy
                - domain: Optional, company website domain

        Returns:
            Dict with:
            - total: Total contacts submitted
            - found: Number of addresses found
            - results: List of results with addresses

        Example:
            skiptrace_batch_lookup([
                {"first_name": "John", "last_name": "Doe", "company": "Acme Corp"},
                {"first_name": "Jane", "last_name": "Smith", "company": "Tech Inc"}
            ])
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not contacts:
            return {"error": "Contacts list is required"}

        if len(contacts) > 100:
            return {"error": "Maximum batch size is 100 contacts"}

        for contact in contacts:
            if not contact.get("first_name") or not contact.get("last_name"):
                return {"error": "Each contact must have first_name and last_name"}

        try:
            return client.batch_lookup(contacts)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def skiptrace_parse_csv(
        csv_content: str,
        first_name_col: str = "first_name",
        last_name_col: str = "last_name",
        company_col: str | None = "company",
    ) -> dict:
        """
        Parse a CSV file content for batch skip trace lookup.

        Args:
            csv_content: CSV file content as string
            first_name_col: Column name for first names (default: "first_name")
            last_name_col: Column name for last names (default: "last_name")
            company_col: Column name for companies (default: "company")

        Returns:
            Dict with:
            - total: Total rows parsed
            - contacts: List of contact dicts ready for skiptrace_batch_lookup
            - errors: List of row parsing errors

        Example:
            skiptrace_parse_csv(
                csv_content="first_name,last_name,company\\nJohn,Doe,Acme Corp",
                first_name_col="first_name",
                last_name_col="last_name",
                company_col="company"
            )
        """
        contacts = []
        errors = []

        try:
            lines = csv_content.strip().split("\n")
            if not lines:
                return {"error": "CSV content is empty"}

            reader = csv.DictReader(lines)

            for i, row in enumerate(reader, start=2):
                try:
                    contact = {
                        "first_name": row.get(first_name_col, "").strip(),
                        "last_name": row.get(last_name_col, "").strip(),
                    }

                    if company_col and row.get(company_col):
                        contact["company"] = row[company_col].strip()

                    if contact["first_name"] and contact["last_name"]:
                        contacts.append(contact)
                    else:
                        errors.append({"row": i, "error": "Missing first_name or last_name"})
                except Exception as e:
                    errors.append({"row": i, "error": str(e)})

            return {
                "total": len(contacts),
                "contacts": contacts,
                "errors": errors,
            }

        except Exception as e:
            return {"error": f"Failed to parse CSV: {e}"}
