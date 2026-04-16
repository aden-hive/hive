"""
Mailchimp Tool - Audience and campaign management via Mailchimp API.

Supports:
- Audience/list management
- Member CRUD with tag support
- Campaign listing and reports

API Reference: https://mailchimp.com/developer/marketing/api/
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _MailchimpClient:
    """Internal client wrapping Mailchimp Marketing API v3 calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        # Extract data center from key, defaulting to us1
        dc = "us1"
        if "-" in api_key:
            dc = api_key.split("-")[-1]
        self._api_base = f"https://{dc}.api.mailchimp.com/3.0"

    @property
    def _auth(self) -> tuple[str, str]:
        # Mailchimp accepts Basic Auth with any username and the api_key as password
        return ("anystring", self._api_key)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Mailchimp API key"}
        if response.status_code == 403:
            return {"error": "Mailchimp API key lacks required permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 400:
            try:
                detail = response.json()
                msg = detail.get("detail", response.text)
                if "errors" in detail:
                    msg += f" (Errors: {detail['errors']})"
            except Exception:
                msg = response.text
            return {"error": f"Bad request: {msg}"}
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Mailchimp API error (HTTP {response.status_code}): {detail}"}
        
        if response.status_code == 204:
            return {"success": True}
        try:
            return response.json()
        except Exception:
            return {"success": True}

    def _get_subscriber_hash(self, email: str) -> str:
        """Calculate the MD5 hash of the lowercase email address."""
        return hashlib.md5(email.lower().encode()).hexdigest()

    def get_audiences(self) -> dict[str, Any]:
        """List all audiences (lists)."""
        response = httpx.get(
            f"{self._api_base}/lists",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_audience(self, list_id: str) -> dict[str, Any]:
        """Get specific audience details."""
        response = httpx.get(
            f"{self._api_base}/lists/{list_id}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_member(
        self,
        list_id: str,
        email: str,
        status: str = "subscribed",
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a new member to a list."""
        payload: dict[str, Any] = {
            "email_address": email,
            "status": status,
        }
        if merge_fields:
            payload["merge_fields"] = merge_fields
        if tags:
            payload["tags"] = tags

        response = httpx.post(
            f"{self._api_base}/lists/{list_id}/members",
            auth=self._auth,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_member(self, list_id: str, email: str) -> dict[str, Any]:
        """Get a member from a list."""
        subscriber_hash = self._get_subscriber_hash(email)
        response = httpx.get(
            f"{self._api_base}/lists/{list_id}/members/{subscriber_hash}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_member(
        self,
        list_id: str,
        email: str,
        status: str | None = None,
        merge_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing member."""
        subscriber_hash = self._get_subscriber_hash(email)
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if merge_fields:
            payload["merge_fields"] = merge_fields

        response = httpx.patch(
            f"{self._api_base}/lists/{list_id}/members/{subscriber_hash}",
            auth=self._auth,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_member_tags(self, list_id: str, email: str, tags: list[str]) -> dict[str, Any]:
        """Update tags for a member."""
        subscriber_hash = self._get_subscriber_hash(email)
        payload: dict[str, Any] = {
            "tags": [{"name": tag, "status": "active"} for tag in tags]
        }
        response = httpx.post(
            f"{self._api_base}/lists/{list_id}/members/{subscriber_hash}/tags",
            auth=self._auth,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_campaigns(self, status: str | None = None) -> dict[str, Any]:
        """List campaigns."""
        params: dict[str, str] = {}
        if status:
            params["status"] = status

        response = httpx.get(
            f"{self._api_base}/campaigns",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_campaign_report(self, campaign_id: str) -> dict[str, Any]:
        """Get details and performance report of a campaign."""
        response = httpx.get(
            f"{self._api_base}/reports/{campaign_id}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Mailchimp tools with the MCP server."""

    def _get_client() -> _MailchimpClient | dict[str, str]:
        """Get a Mailchimp client, or return an error dict if no credentials."""
        api_key = None
        if credentials is not None:
            api_key = credentials.get("mailchimp")
            if api_key is not None and not isinstance(api_key, str):
                raise TypeError(
                    f"Expected string from credentials.get('mailchimp'), got {type(api_key).__name__}"
                )
        if not api_key:
            api_key = os.getenv("MAILCHIMP_API_KEY")

        if not api_key:
            return {
                "error": "Mailchimp API key not configured",
                "help": (
                    "Set MAILCHIMP_API_KEY environment variable or configure via "
                    "credential store. Format: <key>-<dc>"
                ),
            }
        return _MailchimpClient(api_key)

    @mcp.tool()
    def mailchimp_get_audiences() -> dict[str, Any]:
        """
        List all Mailchimp audiences (lists).
        
        Returns:
            Dict containing audiences information.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        try:
            return client.get_audiences()
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_audience(list_id: str) -> dict[str, Any]:
        """
        Get details for a specific Mailchimp audience (list).
        
        Args:
            list_id: The unique ID of the Mailchimp audience.
            
        Returns:
            Dict containing audience particulars.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        if not list_id:
            return {"error": "list_id is required"}
            
        try:
            return client.get_audience(list_id)
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_add_member(
        list_id: str,
        email: str,
        status: str = "subscribed",
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Add a new member to a Mailchimp audience.
        
        Args:
            list_id: The unique ID of the Mailchimp audience.
            email: The email address to add.
            status: Subscriber's status ("subscribed", "unsubscribed", "cleaned", "pending", "transactional"). Default is "subscribed".
            merge_fields: A dictionary of merge fields (e.g., {"FNAME": "John", "LNAME": "Doe"}).
            tags: A list of tags to append to the member.
            
        Returns:
            Dict containing member details or error info.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        if not list_id or not email:
            return {"error": "list_id and email are required"}
            
        try:
            return client.add_member(list_id, email, status, merge_fields, tags)
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_member(list_id: str, email: str) -> dict[str, Any]:
        """
        Retrieve a specific member from a Mailchimp audience.
        
        Args:
            list_id: The unique ID of the Mailchimp audience.
            email: The member's email address.
            
        Returns:
            Dict containing member details or error info.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        if not list_id or not email:
            return {"error": "list_id and email are required"}
            
        try:
            return client.get_member(list_id, email)
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_update_member(
        list_id: str,
        email: str,
        status: str | None = None,
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing member in a Mailchimp audience.
        
        Args:
            list_id: The unique ID of the Mailchimp audience.
            email: The member's email address.
            status: Optional new status for the subscriber (e.g. "unsubscribed").
            merge_fields: Optional dict of merge fields to update.
            tags: Optional list of tags to add to the member.
            
        Returns:
            Dict containing member details or error info.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        if not list_id or not email:
            return {"error": "list_id and email are required"}
            
        try:
            result = client.update_member(list_id, email, status, merge_fields)
            if "error" in result:
                return result
                
            if tags:
                tag_result = client.update_member_tags(list_id, email, tags)
                if "error" in tag_result:
                    return tag_result
                    
            return result
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_list_campaigns(status: str | None = None) -> dict[str, Any]:
        """
        List Mailchimp campaigns.
        
        Args:
            status: Filter campaigns by status (e.g. "save", "paused", "schedule", "sending", "sent").
            
        Returns:
            Dict containing the list of campaigns.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        try:
            return client.list_campaigns(status)
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_campaign_report(campaign_id: str) -> dict[str, Any]:
        """
        Get the report of a specific Mailchimp campaign.
        
        Args:
            campaign_id: The unique ID of the campaign.
            
        Returns:
            Dict containing the campaign report details.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
            
        if not campaign_id:
            return {"error": "campaign_id is required"}
            
        try:
            return client.get_campaign_report(campaign_id)
        except httpx.TimeoutException:
            return {"error": "Mailchimp request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
