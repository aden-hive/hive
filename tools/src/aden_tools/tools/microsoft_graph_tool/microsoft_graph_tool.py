"""
Microsoft Graph Tool - Outlook mail, Teams messaging, and OneDrive file operations.

Supports:
- OAuth 2.0 access token (MICROSOFT_GRAPH_ACCESS_TOKEN)

API Reference: https://learn.microsoft.com/en-us/graph/api/overview
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastmcp import FastMCP

from aden_tools.utils import sanitize_path_param

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Without /me suffix: this module handles non-user endpoints too (teams, $batch).
# Compare with aden_tools.utils.GRAPH_BASE which includes /me.
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("microsoft_graph")
    return os.getenv("MICROSOFT_GRAPH_ACCESS_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get(endpoint: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a GET request to Microsoft Graph API."""
    url = f"{GRAPH_API_BASE}/{endpoint}"
    try:
        resp = httpx.get(url, headers=_headers(token), params=params, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Access token may be expired or invalid."}
        if resp.status_code == 403:
            return {
                "error": f"Forbidden. Missing required permission scope. Details: {resp.text[:300]}"
            }
        if resp.status_code != 200:
            return {"error": f"Microsoft Graph API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Microsoft Graph API timed out"}
    except Exception as e:
        return {"error": f"Microsoft Graph API request failed: {e!s}"}


def _post(endpoint: str, token: str, json_body: dict[str, Any]) -> dict[str, Any]:
    """Make a POST request to Microsoft Graph API."""
    url = f"{GRAPH_API_BASE}/{endpoint}"
    try:
        resp = httpx.post(url, headers=_headers(token), json=json_body, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Access token may be expired or invalid."}
        if resp.status_code == 403:
            return {
                "error": f"Forbidden. Missing required permission scope. Details: {resp.text[:300]}"
            }
        if resp.status_code not in (200, 201, 202):
            return {"error": f"Microsoft Graph API error {resp.status_code}: {resp.text[:500]}"}
        if resp.status_code == 202:
            return {"status": "accepted"}
        if not resp.text:
            return {"status": "success"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Microsoft Graph API timed out"}
    except Exception as e:
        return {"error": f"Microsoft Graph API request failed: {e!s}"}


def _patch(endpoint: str, token: str, json_body: dict[str, Any]) -> dict[str, Any]:
    """Make a PATCH request to Microsoft Graph API."""
    url = f"{GRAPH_API_BASE}/{endpoint}"
    try:
        resp = httpx.patch(url, headers=_headers(token), json=json_body, timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Access token may be expired or invalid."}
        if resp.status_code == 403:
            return {
                "error": f"Forbidden. Missing required permission scope. Details: {resp.text[:300]}"
            }
        if resp.status_code == 404:
            return {"error": "Resource not found"}
        if resp.status_code != 200:
            return {"error": f"Microsoft Graph API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Microsoft Graph API timed out"}
    except Exception as e:
        return {"error": f"Microsoft Graph API request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "MICROSOFT_GRAPH_ACCESS_TOKEN not set",
        "help": "Register an app at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
    }


# Outlook category preset colors (Graph API enum values)
OUTLOOK_CATEGORY_COLORS = [f"preset{i}" for i in range(25)]


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Microsoft Graph tools with the MCP server."""

    # ── Outlook / Mail ──────────────────────────────────────────

    @mcp.tool()
    def outlook_list_messages(
        folder: str = "inbox",
        max_results: int = 20,
        filter_unread: bool = False,
        search: str = "",
    ) -> dict[str, Any]:
        """
        List email messages from an Outlook mailbox folder.

        Args:
            folder: Mail folder name (inbox, sentitems, drafts, deleteditems, archive)
            max_results: Number of messages to return (1-50, default 20)
            filter_unread: If True, only return unread messages
            search: Search query string to filter messages

        Returns:
            Dict with folder name and messages list (id, subject, from, receivedDateTime,
            isRead, hasAttachments, bodyPreview)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        try:
            folder = sanitize_path_param(folder, "folder")
        except ValueError as e:
            return {"error": str(e)}

        max_results = max(1, min(max_results, 50))
        params: dict[str, Any] = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview",
            "$orderby": "receivedDateTime desc",
        }
        if filter_unread:
            params["$filter"] = "isRead eq false"
        if search:
            params["$search"] = f'"{search}"'

        data = _get(f"me/mailFolders/{folder}/messages", token, params)
        if "error" in data:
            return data

        messages = []
        for msg in data.get("value", []):
            from_addr = msg.get("from", {}).get("emailAddress", {})
            messages.append(
                {
                    "id": msg.get("id", ""),
                    "subject": msg.get("subject", ""),
                    "from_name": from_addr.get("name", ""),
                    "from_email": from_addr.get("address", ""),
                    "receivedDateTime": msg.get("receivedDateTime", ""),
                    "isRead": msg.get("isRead", False),
                    "hasAttachments": msg.get("hasAttachments", False),
                    "bodyPreview": msg.get("bodyPreview", ""),
                }
            )
        return {"folder": folder, "messages": messages}

    @mcp.tool()
    def outlook_get_message(
        message_id: str,
    ) -> dict[str, Any]:
        """
        Get full details of an Outlook email message.

        Args:
            message_id: The message ID from outlook_list_messages

        Returns:
            Dict with full message details: subject, from, to, body (HTML), receivedDateTime,
            hasAttachments, importance, categories
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not message_id:
            return {"error": "message_id is required"}

        data = _get(f"me/messages/{message_id}", token)
        if "error" in data:
            return data

        from_addr = data.get("from", {}).get("emailAddress", {})
        to_list = [
            {
                "name": r.get("emailAddress", {}).get("name", ""),
                "email": r.get("emailAddress", {}).get("address", ""),
            }
            for r in data.get("toRecipients", [])
        ]
        return {
            "id": data.get("id", ""),
            "subject": data.get("subject", ""),
            "from_name": from_addr.get("name", ""),
            "from_email": from_addr.get("address", ""),
            "to": to_list,
            "body": data.get("body", {}).get("content", ""),
            "bodyContentType": data.get("body", {}).get("contentType", ""),
            "receivedDateTime": data.get("receivedDateTime", ""),
            "hasAttachments": data.get("hasAttachments", False),
            "importance": data.get("importance", "normal"),
            "categories": data.get("categories", []),
            "isRead": data.get("isRead", False),
        }

    @mcp.tool()
    def outlook_send_mail(
        to: str,
        subject: str,
        body: str,
        body_type: str = "Text",
        cc: str = "",
        save_to_sent: bool = True,
    ) -> dict[str, Any]:
        """
        Send an email via Outlook.

        Args:
            to: Recipient email address (comma-separated for multiple)
            subject: Email subject
            body: Email body content
            body_type: Body content type - Text or HTML (default Text)
            cc: CC email addresses (comma-separated)
            save_to_sent: Whether to save to Sent Items (default True)

        Returns:
            Dict with status confirming the email was sent
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not to or not subject:
            return {"error": "to and subject are required"}

        to_recipients = [
            {"emailAddress": {"address": addr.strip()}} for addr in to.split(",") if addr.strip()
        ]
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": body_type, "content": body},
            "toRecipients": to_recipients,
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr.strip()}}
                for addr in cc.split(",")
                if addr.strip()
            ]

        payload = {"message": message, "saveToSentItems": save_to_sent}
        result = _post("me/sendMail", token, payload)
        if "error" in result:
            return result
        return {"status": "sent", "to": to, "subject": subject}

    # ── Outlook Categories ─────────────────────────────────────

    @mcp.tool()
    def outlook_list_categories() -> dict[str, Any]:
        """
        List all Outlook categories (color-coded tags).

        Categories in Outlook are color-tagged strings that can be applied to
        messages, events, and contacts. Unlike Gmail labels, categories have
        associated preset colors.

        Returns:
            Dict with "categories" list (each with displayName and color) and "count",
            or error dict.
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("me/outlook/masterCategories", token)
        if "error" in data:
            return data

        categories = [
            {
                "displayName": cat.get("displayName", ""),
                "color": cat.get("color", ""),
            }
            for cat in data.get("value", [])
        ]
        return {"categories": categories, "count": len(categories)}

    @mcp.tool()
    def outlook_set_category(
        message_id: str,
        categories: list[str],
    ) -> dict[str, Any]:
        """
        Set categories on an Outlook message.

        Replaces all existing categories on the message with the provided list.
        Pass an empty list to remove all categories.

        Args:
            message_id: The Outlook message ID.
            categories: List of category display names to set on the message.
                        Pass [] to remove all categories.

        Returns:
            Dict with "success" and updated "categories", or error dict.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _patch(f"me/messages/{message_id}", token, {"categories": categories})
        if "error" in data:
            return data

        return {
            "success": True,
            "message_id": message_id,
            "categories": data.get("categories", []),
        }

    @mcp.tool()
    def outlook_create_category(
        display_name: str,
        color: str = "preset0",
    ) -> dict[str, Any]:
        """
        Create a custom Outlook category with a color.

        Outlook categories use preset color values (preset0 through preset24).
        Common color mappings: preset0=Red, preset1=Orange, preset2=Brown,
        preset3=Yellow, preset4=Green, preset5=Teal, preset6=Olive,
        preset7=Blue, preset8=Purple, preset9=Cranberry.

        Args:
            display_name: Name for the new category.
            color: Preset color value (preset0 through preset24). Default: "preset0" (Red).

        Returns:
            Dict with "success", "displayName", and "color", or error dict.
        """
        if not display_name or not display_name.strip():
            return {"error": "display_name is required"}
        if color not in OUTLOOK_CATEGORY_COLORS:
            return {
                "error": f"Invalid color: {color}. Must be preset0 through preset24.",
            }

        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _post(
            "me/outlook/masterCategories", token, {"displayName": display_name, "color": color}
        )
        if "error" in data:
            return data

        return {
            "success": True,
            "displayName": data.get("displayName", display_name),
            "color": data.get("color", color),
        }

    # ── Outlook Focused Inbox ──────────────────────────────────

    @mcp.tool()
    def outlook_get_focused_inbox(
        inbox_type: Literal["focused", "other"] = "focused",
        max_results: int = 25,
    ) -> dict[str, Any]:
        """
        List messages from the Focused or Other inbox.

        Outlook's Focused Inbox automatically sorts important messages into
        "Focused" and less important ones into "Other". This has no Gmail equivalent.

        Args:
            inbox_type: Which inbox to list - "focused" or "other" (default: "focused").
            max_results: Maximum number of messages to return (default: 25, max: 500).

        Returns:
            Dict with "messages" list, "count", and "inbox_type", or error dict.
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        max_results = max(1, min(max_results, 500))
        filter_value = inbox_type.lower()
        params: dict[str, Any] = {
            "$filter": f"inferenceClassification eq '{filter_value}'",
            "$top": max_results,
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,subject,from,receivedDateTime,bodyPreview,isRead,inferenceClassification"
            ),
        }

        data = _get("me/mailFolders/inbox/messages", token, params)
        if "error" in data:
            return data

        messages = [
            {
                "id": msg.get("id", ""),
                "subject": msg.get("subject", ""),
                "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "date": msg.get("receivedDateTime", ""),
                "snippet": msg.get("bodyPreview", ""),
                "is_read": msg.get("isRead", False),
                "classification": msg.get("inferenceClassification", ""),
            }
            for msg in data.get("value", [])
        ]
        return {
            "messages": messages,
            "count": len(messages),
            "inbox_type": inbox_type,
        }

    # ── Outlook Drafts ─────────────────────────────────────────

    @mcp.tool()
    def outlook_create_draft(
        to: str,
        subject: str,
        html: str,
    ) -> dict[str, Any]:
        """
        Create a draft email in Outlook.

        Creates a message in the Drafts folder that can be reviewed and sent
        manually from Outlook. Mirrors gmail_create_draft for Outlook.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            html: Email body as HTML string.

        Returns:
            Dict with "success", "draft_id", and "subject", or error dict.
        """
        if not to or not to.strip():
            return {"error": "Recipient email (to) is required"}
        if not subject or not subject.strip():
            return {"error": "Subject is required"}
        if not html:
            return {"error": "Email body (html) is required"}

        token = _get_token(credentials)
        if not token:
            return _auth_error()

        message_payload = {
            "subject": subject,
            "body": {"contentType": "html", "content": html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }

        data = _post("me/messages", token, message_payload)
        if "error" in data:
            return data

        return {
            "success": True,
            "draft_id": data.get("id", ""),
            "subject": data.get("subject", subject),
        }

    # ── Outlook Batch Operations ───────────────────────────────

    @mcp.tool()
    def outlook_batch_get_messages(
        message_ids: list[str],
    ) -> dict[str, Any]:
        """
        Fetch multiple Outlook messages in a single batch request.

        Uses the Microsoft Graph $batch endpoint to retrieve multiple messages
        efficiently. Mirrors gmail_batch_get_messages for Outlook.

        Args:
            message_ids: List of Outlook message IDs to fetch (max 20 per batch).

        Returns:
            Dict with "messages" list, "count", and "errors" list, or error dict.
        """
        if not message_ids:
            return {"error": "message_ids list is required and must not be empty"}
        if len(message_ids) > 20:
            return {"error": "Maximum 20 message IDs per batch request"}

        for mid in message_ids:
            try:
                sanitize_path_param(mid, "message_id")
            except ValueError as e:
                return {"error": str(e)}

        token = _get_token(credentials)
        if not token:
            return _auth_error()

        requests_payload = [
            {
                "id": str(i),
                "method": "GET",
                "url": (
                    f"/me/messages/{mid}?$select=id,subject,from,"
                    "receivedDateTime,bodyPreview,isRead,"
                    "toRecipients,ccRecipients,body"
                ),
            }
            for i, mid in enumerate(message_ids)
        ]

        try:
            resp = httpx.post(
                f"{GRAPH_API_BASE}/$batch",
                headers=_headers(token),
                json={"requests": requests_payload},
                timeout=60.0,
            )
        except httpx.TimeoutException:
            return {"error": "Batch request to Microsoft Graph API timed out"}
        except Exception as e:
            return {"error": f"Batch request failed: {e!s}"}

        if resp.status_code == 401:
            return {"error": "Unauthorized. Access token may be expired or invalid."}
        if resp.status_code != 200:
            return {
                "error": f"Microsoft Graph API batch error {resp.status_code}: {resp.text[:500]}"
            }

        batch_data = resp.json()
        messages: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for batch_resp in batch_data.get("responses", []):
            resp_id = batch_resp.get("id", "")
            status = batch_resp.get("status", 0)
            body = batch_resp.get("body", {})

            if status == 200:
                to_addrs = [
                    r.get("emailAddress", {}).get("address", "")
                    for r in body.get("toRecipients", [])
                ]
                cc_addrs = [
                    r.get("emailAddress", {}).get("address", "")
                    for r in body.get("ccRecipients", [])
                ]
                msg_body = body.get("body", {})
                messages.append(
                    {
                        "id": body.get("id", ""),
                        "subject": body.get("subject", ""),
                        "from": body.get("from", {}).get("emailAddress", {}).get("address", ""),
                        "to": ", ".join(to_addrs),
                        "cc": ", ".join(cc_addrs),
                        "date": body.get("receivedDateTime", ""),
                        "snippet": body.get("bodyPreview", ""),
                        "is_read": body.get("isRead", False),
                        "body_text": msg_body.get("content", "")
                        if msg_body.get("contentType") == "text"
                        else "",
                        "body_html": msg_body.get("content", "")
                        if msg_body.get("contentType") == "html"
                        else "",
                    }
                )
            else:
                idx = int(resp_id) if resp_id.isdigit() else resp_id
                mid = (
                    message_ids[idx] if isinstance(idx, int) and idx < len(message_ids) else resp_id
                )
                error_body = body.get("error", {})
                errors.append(
                    {
                        "message_id": mid,
                        "error": error_body.get("message", f"HTTP {status}"),
                    }
                )

        return {"messages": messages, "count": len(messages), "errors": errors}

    # ── Teams ───────────────────────────────────────────────────

    @mcp.tool()
    def teams_list_teams() -> dict[str, Any]:
        """
        List all Teams the current user is a member of.

        Returns:
            Dict with teams list (id, displayName, description)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        data = _get("me/joinedTeams", token)
        if "error" in data:
            return data

        teams = []
        for team in data.get("value", []):
            teams.append(
                {
                    "id": team.get("id", ""),
                    "displayName": team.get("displayName", ""),
                    "description": team.get("description", ""),
                }
            )
        return {"teams": teams}

    @mcp.tool()
    def teams_list_channels(
        team_id: str,
    ) -> dict[str, Any]:
        """
        List channels in a Microsoft Teams team.

        Args:
            team_id: The team ID from teams_list_teams

        Returns:
            Dict with team_id and channels list (id, displayName, description, membershipType)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not team_id:
            return {"error": "team_id is required"}

        data = _get(f"teams/{team_id}/channels", token)
        if "error" in data:
            return data

        channels = []
        for ch in data.get("value", []):
            channels.append(
                {
                    "id": ch.get("id", ""),
                    "displayName": ch.get("displayName", ""),
                    "description": ch.get("description", ""),
                    "membershipType": ch.get("membershipType", ""),
                }
            )
        return {"team_id": team_id, "channels": channels}

    @mcp.tool()
    def teams_send_channel_message(
        team_id: str,
        channel_id: str,
        message: str,
        content_type: str = "text",
    ) -> dict[str, Any]:
        """
        Send a message to a Microsoft Teams channel.

        Args:
            team_id: The team ID
            channel_id: The channel ID from teams_list_channels
            message: Message content to send
            content_type: Content type - text or html (default text)

        Returns:
            Dict with status and message id
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not team_id or not channel_id or not message:
            return {"error": "team_id, channel_id, and message are required"}

        payload = {"body": {"contentType": content_type, "content": message}}
        result = _post(f"teams/{team_id}/channels/{channel_id}/messages", token, payload)
        if "error" in result:
            return result
        return {
            "status": "sent",
            "messageId": result.get("id", ""),
            "team_id": team_id,
            "channel_id": channel_id,
        }

    @mcp.tool()
    def teams_get_channel_messages(
        team_id: str,
        channel_id: str,
        max_results: int = 20,
    ) -> dict[str, Any]:
        """
        Get recent messages from a Microsoft Teams channel.

        Args:
            team_id: The team ID
            channel_id: The channel ID
            max_results: Number of messages to return (1-50, default 20)

        Returns:
            Dict with team_id, channel_id, and messages list (id, from, body, createdDateTime)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not team_id or not channel_id:
            return {"error": "team_id and channel_id are required"}

        max_results = max(1, min(max_results, 50))
        data = _get(f"teams/{team_id}/channels/{channel_id}/messages", token, {"$top": max_results})
        if "error" in data:
            return data

        messages = []
        for msg in data.get("value", []):
            from_info = msg.get("from", {}).get("user", {})
            messages.append(
                {
                    "id": msg.get("id", ""),
                    "from_name": from_info.get("displayName", ""),
                    "body": msg.get("body", {}).get("content", ""),
                    "contentType": msg.get("body", {}).get("contentType", ""),
                    "createdDateTime": msg.get("createdDateTime", ""),
                }
            )
        return {"team_id": team_id, "channel_id": channel_id, "messages": messages}

    # ── OneDrive ────────────────────────────────────────────────

    @mcp.tool()
    def onedrive_search_files(
        query: str,
        max_results: int = 20,
    ) -> dict[str, Any]:
        """
        Search for files in the user's OneDrive.

        Args:
            query: Search query string (searches file names and content)
            max_results: Number of results to return (1-50, default 20)

        Returns:
            Dict with query and files list (id, name, size, lastModifiedDateTime,
            webUrl, mimeType, path)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        max_results = max(1, min(max_results, 50))
        data = _get(f"me/drive/root/search(q='{query}')", token, {"$top": max_results})
        if "error" in data:
            return data

        files = []
        for item in data.get("value", []):
            files.append(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "size": item.get("size", 0),
                    "lastModifiedDateTime": item.get("lastModifiedDateTime", ""),
                    "webUrl": item.get("webUrl", ""),
                    "mimeType": item.get("file", {}).get("mimeType", ""),
                    "path": item.get("parentReference", {}).get("path", ""),
                }
            )
        return {"query": query, "files": files}

    @mcp.tool()
    def onedrive_list_files(
        folder_path: str = "",
        max_results: int = 50,
    ) -> dict[str, Any]:
        """
        List files and folders in a OneDrive directory.

        Args:
            folder_path: Path to folder (empty for root, e.g. "Documents/Reports")
            max_results: Number of items to return (1-200, default 50)

        Returns:
            Dict with path and items list (id, name, size, type, lastModifiedDateTime, webUrl)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        max_results = max(1, min(max_results, 200))
        if folder_path:
            endpoint = f"me/drive/root:/{folder_path}:/children"
        else:
            endpoint = "me/drive/root/children"

        data = _get(endpoint, token, {"$top": max_results})
        if "error" in data:
            return data

        items = []
        for item in data.get("value", []):
            item_type = "folder" if "folder" in item else "file"
            items.append(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "size": item.get("size", 0),
                    "type": item_type,
                    "lastModifiedDateTime": item.get("lastModifiedDateTime", ""),
                    "webUrl": item.get("webUrl", ""),
                }
            )
        return {"path": folder_path or "/", "items": items}

    @mcp.tool()
    def onedrive_download_file(
        item_id: str = "",
        file_path: str = "",
    ) -> dict[str, Any]:
        """
        Download a file from OneDrive. Returns the file content as base64 for binary
        files or as text for text files.

        Args:
            item_id: OneDrive item ID (preferred, from search/list results)
            file_path: File path in OneDrive (e.g. "Documents/report.pdf")

        Returns:
            Dict with name, size, content_type, and content (base64-encoded or text)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        if item_id:
            meta_endpoint = f"me/drive/items/{item_id}"
        elif file_path:
            meta_endpoint = f"me/drive/root:/{file_path}"
        else:
            return {"error": "Provide one of: item_id or file_path"}

        # Get metadata first
        meta = _get(meta_endpoint, token)
        if "error" in meta:
            return meta

        # Download content
        download_url = meta.get("@microsoft.graph.downloadUrl", "")
        if not download_url:
            if item_id:
                download_url = f"{GRAPH_API_BASE}/me/drive/items/{item_id}/content"
            else:
                download_url = f"{GRAPH_API_BASE}/me/drive/root:/{file_path}:/content"

        try:
            resp = httpx.get(
                download_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=60.0,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return {"error": f"Download failed with status {resp.status_code}"}

            content_type = meta.get("file", {}).get("mimeType", "application/octet-stream")
            is_text = content_type.startswith("text/") or content_type in (
                "application/json",
                "application/xml",
                "application/javascript",
            )

            return {
                "name": meta.get("name", ""),
                "size": meta.get("size", 0),
                "content_type": content_type,
                "content": resp.text if is_text else base64.b64encode(resp.content).decode("ascii"),
                "encoding": "text" if is_text else "base64",
            }
        except httpx.TimeoutException:
            return {"error": "File download timed out"}
        except Exception as e:
            return {"error": f"Download failed: {e!s}"}

    @mcp.tool()
    def onedrive_upload_file(
        file_path: str,
        content: str,
        content_type: str = "text/plain",
    ) -> dict[str, Any]:
        """
        Upload a small file to OneDrive (up to 4MB). For larger files, use the
        upload session API.

        Args:
            file_path: Destination path in OneDrive (e.g. "Documents/notes.txt")
            content: File content as text
            content_type: MIME type of the content (default text/plain)

        Returns:
            Dict with status, name, id, size, and webUrl of the uploaded file
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not file_path or not content:
            return {"error": "file_path and content are required"}

        url = f"{GRAPH_API_BASE}/me/drive/root:/{file_path}:/content"
        try:
            resp = httpx.put(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": content_type,
                },
                content=content.encode("utf-8"),
                timeout=60.0,
            )
            if resp.status_code not in (200, 201):
                return {"error": f"Upload failed with status {resp.status_code}: {resp.text[:500]}"}

            data = resp.json()
            return {
                "status": "uploaded",
                "name": data.get("name", ""),
                "id": data.get("id", ""),
                "size": data.get("size", 0),
                "webUrl": data.get("webUrl", ""),
            }
        except httpx.TimeoutException:
            return {"error": "File upload timed out"}
        except Exception as e:
            return {"error": f"Upload failed: {e!s}"}
