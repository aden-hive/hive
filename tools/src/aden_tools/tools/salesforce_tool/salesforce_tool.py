"""
Salesforce CRM Tool - Leads, Contacts, Opportunities, and SOQL queries.

Supports:
- OAuth2 Bearer access tokens (SALESFORCE_ACCESS_TOKEN)
- Instance URL (SALESFORCE_INSTANCE_URL)

API Reference: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_VERSION = "v62.0"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str] | dict[str, str]:
    """Return (access_token, instance_url) or an error dict."""
    if credentials is not None:
        token = credentials.get("salesforce")
        instance_url = credentials.get("salesforce_instance_url")
    else:
        token = os.getenv("SALESFORCE_ACCESS_TOKEN")
        instance_url = os.getenv("SALESFORCE_INSTANCE_URL")

    if not token or not instance_url:
        return {
            "error": "Salesforce credentials not configured",
            "help": (
                "Set SALESFORCE_ACCESS_TOKEN and SALESFORCE_INSTANCE_URL "
                "environment variables or configure via credential store"
            ),
        }
    # Strip trailing slash from instance URL
    instance_url = instance_url.rstrip("/")
    return token, instance_url


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 204:
        return {"success": True}
    if resp.status_code == 401:
        return {"error": "Invalid or expired Salesforce access token"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this Salesforce resource"}
    if resp.status_code == 404:
        return {"error": "Salesforce resource not found"}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            if isinstance(body, list) and body:
                detail = body[0].get("message", resp.text)
            else:
                detail = resp.text
        except Exception:
            detail = resp.text
        return {"error": f"Salesforce API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Salesforce CRM tools with the MCP server."""

    @mcp.tool()
    def salesforce_soql_query(
        query: str,
        next_records_url: str = "",
    ) -> dict:
        """
        Execute a SOQL query against Salesforce.

        Args:
            query: SOQL query string (e.g. "SELECT Id, Name FROM Lead LIMIT 10").
                   Ignored when next_records_url is provided.
            next_records_url: Pagination URL from a previous query response.
                              When provided, fetches the next page of results.

        Returns:
            Dict with totalSize, done, records, and optionally nextRecordsUrl.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not query and not next_records_url:
            return {"error": "Either query or next_records_url is required"}

        try:
            if next_records_url:
                url = f"{instance_url}{next_records_url}"
                resp = httpx.get(url, headers=_headers(token), timeout=30.0)
            else:
                url = f"{instance_url}/services/data/{API_VERSION}/query/"
                resp = httpx.get(
                    url,
                    headers=_headers(token),
                    params={"q": query},
                    timeout=30.0,
                )
            result = _handle_response(resp)
            if "error" in result:
                return result

            output: dict[str, Any] = {
                "total_size": result.get("totalSize", 0),
                "done": result.get("done", True),
                "records": result.get("records", []),
            }
            if result.get("nextRecordsUrl"):
                output["next_records_url"] = result["nextRecordsUrl"]
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_record(
        object_type: str,
        record_id: str,
        fields: str = "",
    ) -> dict:
        """
        Get a single Salesforce record by its ID.

        Args:
            object_type: SObject type (e.g. "Lead", "Contact", "Account", "Opportunity").
            record_id: The 15 or 18-character Salesforce record ID.
            fields: Comma-separated field names to return (optional).

        Returns:
            Dict with the record fields.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type or not record_id:
            return {"error": "object_type and record_id are required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{object_type}/{record_id}"
            params = {}
            if fields:
                params["fields"] = fields
            resp = httpx.get(url, headers=_headers(token), params=params, timeout=30.0)
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_create_record(
        object_type: str,
        fields: dict[str, Any],
    ) -> dict:
        """
        Create a new Salesforce record.

        Args:
            object_type: SObject type (e.g. "Lead", "Contact", "Account").
            fields: Dict of field name to value (e.g. {"LastName": "Doe", "Company": "Acme"}).

        Returns:
            Dict with id, success, and errors from Salesforce.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type:
            return {"error": "object_type is required"}
        if not fields:
            return {"error": "fields dict is required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{object_type}"
            resp = httpx.post(url, headers=_headers(token), json=fields, timeout=30.0)
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_update_record(
        object_type: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict:
        """
        Update fields on an existing Salesforce record.

        Args:
            object_type: SObject type (e.g. "Lead", "Contact").
            record_id: The 15 or 18-character Salesforce record ID.
            fields: Dict of field name to new value (e.g. {"Status": "Contacted"}).

        Returns:
            Dict with success status or error.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type or not record_id:
            return {"error": "object_type and record_id are required"}
        if not fields:
            return {"error": "fields dict is required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{object_type}/{record_id}"
            resp = httpx.patch(url, headers=_headers(token), json=fields, timeout=30.0)
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_describe_object(
        object_type: str,
    ) -> dict:
        """
        Get metadata for a Salesforce SObject type (fields, types, picklist values).

        Args:
            object_type: SObject type (e.g. "Lead", "Contact", "Account", "Opportunity").

        Returns:
            Dict with name, label, fields list, and record type info.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type:
            return {"error": "object_type is required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{object_type}/describe"
            resp = httpx.get(url, headers=_headers(token), timeout=30.0)
            result = _handle_response(resp)
            if "error" in result:
                return result

            # Return a slimmed-down view of the most useful metadata
            fields_summary = []
            for f in result.get("fields", [])[:200]:
                entry: dict[str, Any] = {
                    "name": f.get("name"),
                    "label": f.get("label"),
                    "type": f.get("type"),
                    "required": not f.get("nillable", True) and f.get("createable", False),
                }
                if f.get("picklistValues"):
                    entry["picklist_values"] = [
                        pv["value"] for pv in f["picklistValues"] if pv.get("active")
                    ]
                fields_summary.append(entry)

            return {
                "name": result.get("name"),
                "label": result.get("label"),
                "key_prefix": result.get("keyPrefix"),
                "createable": result.get("createable"),
                "updateable": result.get("updateable"),
                "field_count": len(result.get("fields", [])),
                "fields": fields_summary,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_list_objects() -> dict:
        """
        List all available SObject types in the Salesforce org.

        Returns:
            Dict with a list of SObject names, labels, and key prefixes.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/"
            resp = httpx.get(url, headers=_headers(token), timeout=30.0)
            result = _handle_response(resp)
            if "error" in result:
                return result

            sobjects = []
            for obj in result.get("sobjects", []):
                sobjects.append(
                    {
                        "name": obj.get("name"),
                        "label": obj.get("label"),
                        "key_prefix": obj.get("keyPrefix"),
                        "queryable": obj.get("queryable"),
                        "createable": obj.get("createable"),
                        "custom": obj.get("custom"),
                    }
                )

            return {"count": len(sobjects), "sobjects": sobjects}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_delete_record(
        object_type: str,
        record_id: str,
    ) -> dict:
        """
        Delete a Salesforce record by its ID.

        Args:
            object_type: SObject type (e.g. "Lead", "Contact", "Account").
            record_id: The 15 or 18-character Salesforce record ID.

        Returns:
            Dict with success status or error.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type or not record_id:
            return {"error": "object_type and record_id are required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{object_type}/{record_id}"
            resp = httpx.delete(url, headers=_headers(token), timeout=30.0)
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_search_records(
        search_query: str,
    ) -> dict:
        """
        Full-text search across Salesforce records using SOSL.

        More flexible than SOQL for keyword searches across multiple objects.

        Args:
            search_query: SOSL search string.
                e.g. "FIND {John Smith} IN ALL FIELDS RETURNING Contact(Id, Name), Lead(Id, Name)"

        Returns:
            Dict with search results grouped by SObject type.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not search_query:
            return {"error": "search_query is required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/search/"
            resp = httpx.get(
                url,
                headers=_headers(token),
                params={"q": search_query},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            # Result is a list of search results
            if isinstance(result, list):
                return {"records": result, "count": len(result)}
            records = result.get("searchRecords", [])
            return {"records": records, "count": len(records)}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def salesforce_get_record_count(
        object_type: str,
    ) -> dict:
        """
        Get the total number of records for a Salesforce SObject type.

        Uses SELECT COUNT() for an efficient count without returning records.

        Args:
            object_type: SObject type (e.g. "Lead", "Contact", "Account", "Opportunity").

        Returns:
            Dict with total_size count or error.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, instance_url = creds

        if not object_type:
            return {"error": "object_type is required"}

        try:
            url = f"{instance_url}/services/data/{API_VERSION}/query/"
            resp = httpx.get(
                url,
                headers=_headers(token),
                params={"q": f"SELECT COUNT() FROM {object_type}"},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "object_type": object_type,
                "total_size": result.get("totalSize", 0),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
