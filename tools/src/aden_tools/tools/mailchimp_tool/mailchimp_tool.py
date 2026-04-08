"""
Mailchimp Tool - Manage audiences, members, and campaigns via Mailchimp Marketing API.

Supports:
- API Key authentication (MAILCHIMP_API_KEY)

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


def _dc_from_key(api_key: str) -> str:
    """Extract data center prefix from Mailchimp API key (e.g. 'us1' from 'key-us1')."""
    parts = api_key.strip().split("-")
    return parts[-1] if len(parts) > 1 else "us1"


def _subscriber_hash(email: str) -> str:
    """Return MD5 hash of lowercased email as required by Mailchimp API."""
    return hashlib.md5(email.lower().encode()).hexdigest()


class _MailchimpClient:
    """Internal client wrapping Mailchimp API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._dc = _dc_from_key(api_key)
        self._base_url = f"https://{self._dc}.api.mailchimp.com/3.0"
        self._auth = ("anystring", self._api_key)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Mailchimp API response."""
        if response.status_code == 401:
            return {"error": "Invalid Mailchimp API key"}
        if response.status_code == 403:
            return {"error": "Access forbidden"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code not in (200, 201, 204):
            return {"error": f"HTTP error {response.status_code}: {response.text}"}
        if response.status_code == 204 or not response.content:
            return {"success": True}
        return response.json()

    def ping(self) -> dict[str, Any]:
        """Verify credentials."""
        response = httpx.get(
            f"{self._base_url}/ping",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_audiences(
        self,
        count: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List all audiences."""
        params = {"count": count, "offset": offset}
        response = httpx.get(
            f"{self._base_url}/lists",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_audience(self, list_id: str) -> dict[str, Any]:
        """Get single audience details."""
        response = httpx.get(
            f"{self._base_url}/lists/{list_id}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_members(
        self,
        list_id: str,
        status: str | None = None,
        count: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List members with status filter."""
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status:
            params["status"] = status
        response = httpx.get(
            f"{self._base_url}/lists/{list_id}/members",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_member(self, list_id: str, email: str) -> dict[str, Any]:
        """Get member by email."""
        sub_hash = _subscriber_hash(email)
        response = httpx.get(
            f"{self._base_url}/lists/{list_id}/members/{sub_hash}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def add_or_update_member(
        self,
        list_id: str,
        email: str,
        status_if_new: str = "subscribed",
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upsert member with tags support."""
        sub_hash = _subscriber_hash(email)
        body: dict[str, Any] = {
            "email_address": email,
            "status_if_new": status_if_new,
        }
        if merge_fields:
            body["merge_fields"] = merge_fields

        response = httpx.put(
            f"{self._base_url}/lists/{list_id}/members/{sub_hash}",
            auth=self._auth,
            json=body,
            timeout=30.0,
        )

        result = self._handle_response(response)
        if "error" in result:
            return result

        if tags:
            tag_body = {
                "tags": [{"name": tag, "status": "active"} for tag in tags]
            }
            tag_response = httpx.post(
                f"{self._base_url}/lists/{list_id}/members/{sub_hash}/tags",
                auth=self._auth,
                json=tag_body,
                timeout=30.0,
            )
            tag_result = self._handle_response(tag_response)
            if "error" in tag_result:
                return {"error": f"Member upserted, but tags failed: {tag_result['error']}"}

        return result

    def update_member_status(self, list_id: str, email: str, status: str) -> dict[str, Any]:
        """Change subscription status."""
        sub_hash = _subscriber_hash(email)
        body = {"status": status}
        response = httpx.patch(
            f"{self._base_url}/lists/{list_id}/members/{sub_hash}",
            auth=self._auth,
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_member(self, list_id: str, email: str) -> dict[str, Any]:
        """Delete a member permanently."""
        sub_hash = _subscriber_hash(email)
        response = httpx.post(
            f"{self._base_url}/lists/{list_id}/members/{sub_hash}/actions/delete-permanent",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def list_campaigns(
        self,
        status: str | None = None,
        count: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List campaigns with status filter."""
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status:
            params["status"] = status
        response = httpx.get(
            f"{self._base_url}/campaigns",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_campaign_report(self, campaign_id: str) -> dict[str, Any]:
        """Get opens/clicks/bounces stats."""
        response = httpx.get(
            f"{self._base_url}/reports/{campaign_id}",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)

    def send_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Send a ready campaign."""
        response = httpx.post(
            f"{self._base_url}/campaigns/{campaign_id}/actions/send",
            auth=self._auth,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Mailchimp tools with the MCP server."""

    def _get_api_key() -> str | None:
        if credentials is not None:
            key = credentials.get("mailchimp")
            if key is not None and not isinstance(key, str):
                raise TypeError(f"Expected string from credentials, got {type(key).__name__}")
            return key
        return os.getenv("MAILCHIMP_API_KEY")

    def _get_client() -> _MailchimpClient | dict[str, str]:
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Mailchimp credentials not configured",
                "help": (
                    "Set MAILCHIMP_API_KEY environment variable or configure via credential store. "
                ),
            }
        return _MailchimpClient(api_key)

    @mcp.tool()
    def mailchimp_ping() -> dict:
        """
        Verify Mailchimp API credentials.

        Returns:
            Dict with success status or error.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.ping()
            if "error" in result:
                return result
            return {"success": True, "health_status": result.get("health_status")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_list_audiences(
        count: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        List all audiences (lists) in Mailchimp.

        Args:
            count: Number of results to return (default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with audiences list.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_audiences(count, offset)
            if "error" in result:
                return result
            audiences = result.get("lists", [])
            return {
                "count": len(audiences),
                "total": result.get("total_items", len(audiences)),
                "audiences": [
                    {
                        "id": audience.get("id"),
                        "name": audience.get("name"),
                        "member_count": audience.get("stats", {}).get("member_count"),
                        "date_created": audience.get("date_created"),
                    }
                    for audience in audiences
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_audience(list_id: str) -> dict:
        """
        Get details of a single audience by its ID.

        Args:
            list_id: The unique ID of the audience (list)

        Returns:
            Dict with audience details.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_audience(list_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "name": result.get("name"),
                "stats": result.get("stats"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_list_members(
        list_id: str,
        status: str = "",
        count: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        List members of a specific audience, optionally filtered by status.

        Args:
            list_id: The ID of the audience (list)
            status: Filter by status (e.g., 'subscribed', 'unsubscribed',
                'cleaned', 'pending', 'transactional')
            count: Number of results to return (default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with lists of members.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_members(list_id, status or None, count, offset)
            if "error" in result:
                return result
            members = result.get("members", [])
            return {
                "count": len(members),
                "total": result.get("total_items", len(members)),
                "members": [
                    {
                        "id": m.get("id"),
                        "email_address": m.get("email_address"),
                        "status": m.get("status"),
                        "last_changed": m.get("last_changed"),
                    }
                    for m in members
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_member(list_id: str, email: str) -> dict:
        """
        Get details of an audience member by their email address.

        Args:
            list_id: The ID of the audience
            email: The email address of the member

        Returns:
            Dict with member details.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_member(list_id, email)
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "email_address": result.get("email_address"),
                "status": result.get("status"),
                "merge_fields": result.get("merge_fields"),
                "tags": [tag.get("name") for tag in result.get("tags", [])],
                "last_changed": result.get("last_changed"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_add_or_update_member(
        list_id: str,
        email: str,
        status_if_new: str = "subscribed",
        merge_fields: str = "",
        tags: str = "",
    ) -> dict:
        """
        Add a new member or update an existing member.

        Args:
            list_id: The ID of the audience
            email: The email address of the member
            status_if_new: The status if the member is newly added (e.g.,
                'subscribed', 'pending'). Default is 'subscribed'.
            merge_fields: Optional JSON string or dictionary representing
                merge fields mapping. E.g., '{"FNAME": "John", "LNAME": "Doe"}'
            tags: Optional comma-separated tags to add to the member

        Returns:
            Dict with success status or error.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        parsed_merge_fields = None
        if merge_fields:
            import json
            try:
                is_string = isinstance(merge_fields, str)
                parsed_merge_fields = json.loads(merge_fields) if is_string else merge_fields
            except json.JSONDecodeError:
                return {"error": "merge_fields must be a valid JSON string"}

        parsed_tags = None
        if tags:
            parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

        try:
            result = client.add_or_update_member(
                list_id, email, status_if_new, parsed_merge_fields, parsed_tags
            )
            if "error" in result:
                return result
            return {"success": True, "email": email, "id": result.get("id")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_update_member_status(list_id: str, email: str, status: str) -> dict:
        """
        Change the subscription status of a member.

        Args:
            list_id: The ID of the audience
            email: The email address of the member
            status: New status (one of: 'subscribed', 'unsubscribed',
                'cleaned', 'pending', 'transactional')

        Returns:
            Dict with success status or error.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.update_member_status(list_id, email, status)
            if "error" in result:
                return result
            return {"success": True, "email": email, "new_status": result.get("status")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_delete_member(list_id: str, email: str) -> dict:
        """
        Permanently delete a member from an audience.

        Args:
            list_id: The ID of the audience
            email: The email address of the member

        Returns:
            Dict with success status or error.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_member(list_id, email)
            if "error" in result:
                return result
            return {"success": True, "email": email, "status": "deleted"}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_list_campaigns(
        status: str = "",
        count: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        List all campaigns, optionally filtered by status.

        Args:
            status: Filter by status (e.g., 'save', 'paused', 'schedule', 'sending', 'sent')
            count: Number of results to return (default 50)
            offset: Pagination offset (default 0)

        Returns:
            Dict with campaigns list.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.list_campaigns(status or None, count, offset)
            if "error" in result:
                return result
            campaigns = result.get("campaigns", [])
            return {
                "count": len(campaigns),
                "total": result.get("total_items", len(campaigns)),
                "campaigns": [
                    {
                        "id": c.get("id"),
                        "status": c.get("status"),
                        "type": c.get("type"),
                        "send_time": c.get("send_time"),
                        "subject_line": c.get("settings", {}).get("subject_line"),
                        "title": c.get("settings", {}).get("title"),
                    }
                    for c in campaigns
                ],
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_get_campaign_report(campaign_id: str) -> dict:
        """
        Get opens, clicks, bounces, and other stats for a campaign.

        Args:
            campaign_id: The ID of the campaign

        Returns:
            Dict with campaign report.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_campaign_report(campaign_id)
            if "error" in result:
                return result
            return {
                "success": True,
                "id": result.get("id"),
                "emails_sent": result.get("emails_sent"),
                "abuses": result.get("abuses"),
                "bounces": result.get("bounces"),
                "forwards": result.get("forwards"),
                "opens": result.get("opens"),
                "clicks": result.get("clicks"),
                "unsubscribed": result.get("unsubscribed"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mailchimp_send_campaign(campaign_id: str) -> dict:
        """
        Send a ready campaign.

        Args:
            campaign_id: The ID of the campaign to send

        Returns:
            Dict with success status or error.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.send_campaign(campaign_id)
            if "error" in result:
                return result
            return {"success": True, "campaign_id": campaign_id, "status": "sent"}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
