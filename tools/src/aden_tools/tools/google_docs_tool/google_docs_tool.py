"""
Google Docs Tool - Create and manage Google Docs documents via Google Docs API v1.

Supports:
- OAuth2 tokens via the credential store
- Service account JSON credentials (GOOGLE_SERVICE_ACCOUNT_JSON)
- Direct access token (GOOGLE_DOCS_ACCESS_TOKEN)

API Reference: https://developers.google.com/docs/api/reference/rest

Note on indexing: The Google Docs API uses 1-based indexing for document content.
For complex updates, it's recommended to "write backwards" (start from the end
of the document) to avoid index shifting issues.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GOOGLE_DOCS_API_BASE = "https://docs.googleapis.com/v1"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


class _GoogleDocsClient:
    """Internal client wrapping Google Docs API v1 calls."""

    def __init__(self, access_token: str):
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Google access token"}
        if response.status_code == 403:
            return {
                "error": "Insufficient permissions. Check your Google API scopes. "
                "Required scopes: https://www.googleapis.com/auth/documents"
            }
        if response.status_code == 404:
            return {"error": "Document not found"}
        if response.status_code == 429:
            return {"error": "Google API rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                error_data = response.json()
                detail = error_data.get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Google Docs API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def create_document(self, title: str) -> dict[str, Any]:
        """Create a new blank document with a specified title."""
        response = httpx.post(
            f"{GOOGLE_DOCS_API_BASE}/documents",
            headers=self._headers,
            json={"title": title},
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_document(self, document_id: str) -> dict[str, Any]:
        """Retrieve the full structural content, metadata, and elements of a document."""
        response = httpx.get(
            f"{GOOGLE_DOCS_API_BASE}/documents/{document_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def batch_update(
        self, document_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Execute multiple requests in a single atomic operation."""
        response = httpx.post(
            f"{GOOGLE_DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers,
            json={"requests": requests},
            timeout=60.0,
        )
        return self._handle_response(response)

    def insert_text(
        self,
        document_id: str,
        text: str,
        index: int | None = None,
        segment_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert text at a specific index or at the end of the document."""
        location: dict[str, Any] = {}
        if segment_id:
            location["segmentId"] = segment_id
        if index is not None:
            location["index"] = index
        else:
            # Insert at end - we need to get doc first to find the end index
            doc = self.get_document(document_id)
            if "error" in doc:
                return doc
            # Get the end index from the document body
            body = doc.get("body", {})
            content = body.get("content", [])
            if content:
                last_element = content[-1]
                end_index = last_element.get("endIndex", 1)
                location["index"] = end_index - 1  # Insert before the final newline
            else:
                location["index"] = 1

        request = {
            "insertText": {
                "location": location,
                "text": text,
            }
        }
        return self.batch_update(document_id, [request])

    def replace_all_text(
        self,
        document_id: str,
        find_text: str,
        replace_text: str,
        match_case: bool = True,
    ) -> dict[str, Any]:
        """Global find-and-replace (ideal for populating templates with dynamic data)."""
        request = {
            "replaceAllText": {
                "containsText": {
                    "text": find_text,
                    "matchCase": match_case,
                },
                "replaceText": replace_text,
            }
        }
        return self.batch_update(document_id, [request])

    def insert_image(
        self,
        document_id: str,
        image_uri: str,
        index: int,
        width_pt: float | None = None,
        height_pt: float | None = None,
    ) -> dict[str, Any]:
        """Insert an image into the document body via URI."""
        request: dict[str, Any] = {
            "insertInlineImage": {
                "location": {"index": index},
                "uri": image_uri,
            }
        }
        if width_pt is not None or height_pt is not None:
            object_size: dict[str, Any] = {}
            if width_pt is not None:
                object_size["width"] = {"magnitude": width_pt, "unit": "PT"}
            if height_pt is not None:
                object_size["height"] = {"magnitude": height_pt, "unit": "PT"}
            request["insertInlineImage"]["objectSize"] = object_size

        return self.batch_update(document_id, [request])

    def format_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        font_size_pt: float | None = None,
        foreground_color: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Apply styling (bold, italic, font size, colors) to specific text ranges."""
        text_style: dict[str, Any] = {}
        fields: list[str] = []

        if bold is not None:
            text_style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            text_style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            text_style["underline"] = underline
            fields.append("underline")
        if font_size_pt is not None:
            text_style["fontSize"] = {"magnitude": font_size_pt, "unit": "PT"}
            fields.append("fontSize")
        if foreground_color is not None:
            text_style["foregroundColor"] = {"color": {"rgbColor": foreground_color}}
            fields.append("foregroundColor")

        if not fields:
            return {"error": "No formatting options specified"}

        request = {
            "updateTextStyle": {
                "range": {
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "textStyle": text_style,
                "fields": ",".join(fields),
            }
        }
        return self.batch_update(document_id, [request])

    def create_list(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bullet_preset: str = "BULLET_DISC_CIRCLE_SQUARE",
    ) -> dict[str, Any]:
        """Create or modify bulleted and numbered lists within the document."""
        request = {
            "createParagraphBullets": {
                "range": {
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "bulletPreset": bullet_preset,
            }
        }
        return self.batch_update(document_id, [request])

    def add_comment(
        self,
        document_id: str,
        content: str,
        quoted_text: str | None = None,
    ) -> dict[str, Any]:
        """Create a comment on the document (via Drive API)."""
        body: dict[str, Any] = {"content": content}
        if quoted_text:
            body["quotedFileContent"] = {"value": quoted_text}

        response = httpx.post(
            f"{GOOGLE_DRIVE_API_BASE}/files/{document_id}/comments",
            headers=self._headers,
            params={"fields": "*"},
            json=body,
            timeout=30.0,
        )
        return self._handle_response(response)

    def export_document(
        self,
        document_id: str,
        mime_type: str = "application/pdf",
    ) -> dict[str, Any]:
        """Export the document to different formats (PDF, DOCX, TXT)."""
        response = httpx.get(
            f"{GOOGLE_DRIVE_API_BASE}/files/{document_id}/export",
            headers=self._headers,
            params={"mimeType": mime_type},
            timeout=60.0,
        )
        if response.status_code == 200:
            # Return base64-encoded content for binary formats
            import base64

            return {
                "document_id": document_id,
                "mime_type": mime_type,
                "content_base64": base64.b64encode(response.content).decode("utf-8"),
                "size_bytes": len(response.content),
            }
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Docs tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Google access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("google_docs")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('google_docs'), "
                    f"got {type(token).__name__}"
                )
            return token
        # Try environment variables
        token = os.getenv("GOOGLE_DOCS_ACCESS_TOKEN")
        if token:
            return token
        # Try service account JSON (would need additional handling for token exchange)
        service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account:
            # For service accounts, we'd need to implement JWT token exchange
            # This is a simplified version that expects a pre-exchanged token
            try:
                sa_data = json.loads(service_account)
                return sa_data.get("access_token")
            except json.JSONDecodeError:
                return None
        return None

    def _get_client() -> _GoogleDocsClient | dict[str, str]:
        """Get a Google Docs client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Google Docs credentials not configured",
                "help": (
                    "Set GOOGLE_DOCS_ACCESS_TOKEN environment variable "
                    "or configure via credential store. "
                    "Get credentials at: https://console.cloud.google.com/apis/credentials"
                ),
            }
        return _GoogleDocsClient(token)

    # --- Document Management ---

    @mcp.tool()
    def google_docs_create_document(title: str) -> dict:
        """
        Create a new blank Google Docs document with a specified title.

        Args:
            title: The title for the new document

        Returns:
            Dict with document ID and metadata, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.create_document(title)
            if "error" not in result:
                return {
                    "document_id": result.get("documentId"),
                    "title": result.get("title"),
                    "document_url": f"https://docs.google.com/document/d/{result.get('documentId')}/edit",
                }
            return result
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_get_document(document_id: str) -> dict:
        """
        Retrieve the full structural content, metadata, and elements of a document.

        Args:
            document_id: The ID of the Google Docs document

        Returns:
            Dict with document content and structure, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_document(document_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_insert_text(
        document_id: str,
        text: str,
        index: int | None = None,
    ) -> dict:
        """
        Insert text at a specific index or at the end of the document.

        Note: Google Docs uses 1-based indexing. Index 1 is the start of the document.

        Args:
            document_id: The ID of the Google Docs document
            text: The text to insert
            index: The index where to insert text (1-based). If None, appends to end.

        Returns:
            Dict with update result, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.insert_text(document_id, text, index)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_replace_all_text(
        document_id: str,
        find_text: str,
        replace_text: str,
        match_case: bool = True,
    ) -> dict:
        """
        Global find-and-replace (ideal for populating templates with dynamic data).

        Use this for template placeholders like {{Customer_Name}} or {{Date}}.

        Args:
            document_id: The ID of the Google Docs document
            find_text: The text to find (e.g., "{{Customer_Name}}")
            replace_text: The text to replace with (e.g., "John Doe")
            match_case: Whether to match case exactly (default: True)

        Returns:
            Dict with number of replacements made, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.replace_all_text(document_id, find_text, replace_text, match_case)
            if "error" not in result:
                # Extract replacement count from response
                replies = result.get("replies", [])
                occurrences = 0
                for reply in replies:
                    replace_reply = reply.get("replaceAllText", {})
                    occurrences += replace_reply.get("occurrencesChanged", 0)
                return {
                    "document_id": document_id,
                    "find_text": find_text,
                    "replace_text": replace_text,
                    "occurrences_replaced": occurrences,
                }
            return result
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_insert_image(
        document_id: str,
        image_uri: str,
        index: int,
        width_pt: float | None = None,
        height_pt: float | None = None,
    ) -> dict:
        """
        Insert an image into the document body via URI.

        Note: The image URI must be publicly accessible by Google's servers.

        Args:
            document_id: The ID of the Google Docs document
            image_uri: Public URL of the image to insert
            index: The index where to insert the image (1-based)
            width_pt: Optional width in points
            height_pt: Optional height in points

        Returns:
            Dict with update result, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.insert_image(document_id, image_uri, index, width_pt, height_pt)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_format_text(
        document_id: str,
        start_index: int,
        end_index: int,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        font_size_pt: float | None = None,
        foreground_color_red: float | None = None,
        foreground_color_green: float | None = None,
        foreground_color_blue: float | None = None,
    ) -> dict:
        """
        Apply styling (bold, italic, font size, colors) to specific text ranges.

        Args:
            document_id: The ID of the Google Docs document
            start_index: Start index of the text range (1-based, inclusive)
            end_index: End index of the text range (1-based, exclusive)
            bold: Set text to bold (True/False/None to skip)
            italic: Set text to italic (True/False/None to skip)
            underline: Set text to underlined (True/False/None to skip)
            font_size_pt: Font size in points (e.g., 12.0)
            foreground_color_red: Red component (0.0-1.0)
            foreground_color_green: Green component (0.0-1.0)
            foreground_color_blue: Blue component (0.0-1.0)

        Returns:
            Dict with update result, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        foreground_color = None
        if any(
            c is not None
            for c in [foreground_color_red, foreground_color_green, foreground_color_blue]
        ):
            foreground_color = {
                "red": foreground_color_red or 0.0,
                "green": foreground_color_green or 0.0,
                "blue": foreground_color_blue or 0.0,
            }

        try:
            return client.format_text(
                document_id,
                start_index,
                end_index,
                bold=bold,
                italic=italic,
                underline=underline,
                font_size_pt=font_size_pt,
                foreground_color=foreground_color,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_batch_update(
        document_id: str,
        requests_json: str,
    ) -> dict:
        """
        Execute multiple requests (inserts, deletes, formatting) in a single atomic operation.

        This is the most powerful tool for complex document modifications.
        See: https://developers.google.com/docs/api/reference/rest/v1/documents/batchUpdate

        Args:
            document_id: The ID of the Google Docs document
            requests_json: JSON string containing an array of request objects

        Returns:
            Dict with batch update result, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            requests = json.loads(requests_json)
            if not isinstance(requests, list):
                return {"error": "requests_json must be a JSON array of request objects"}
            return client.batch_update(document_id, requests)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}"}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_create_list(
        document_id: str,
        start_index: int,
        end_index: int,
        list_type: str = "bullet",
    ) -> dict:
        """
        Create or modify bulleted and numbered lists within the document.

        Args:
            document_id: The ID of the Google Docs document
            start_index: Start index of the paragraphs to convert (1-based)
            end_index: End index of the paragraphs to convert (1-based)
            list_type: Type of list - "bullet" or "numbered"

        Returns:
            Dict with update result, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        bullet_presets = {
            "bullet": "BULLET_DISC_CIRCLE_SQUARE",
            "numbered": "NUMBERED_DECIMAL_ALPHA_ROMAN",
        }
        preset = bullet_presets.get(list_type.lower(), "BULLET_DISC_CIRCLE_SQUARE")

        try:
            return client.create_list(document_id, start_index, end_index, preset)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_add_comment(
        document_id: str,
        content: str,
        quoted_text: str | None = None,
    ) -> dict:
        """
        Create a comment or anchor a discussion thread to a specific text segment.

        Note: This uses the Google Drive API for comments.

        Args:
            document_id: The ID of the Google Docs document
            content: The comment text
            quoted_text: Optional text from the document to anchor the comment to

        Returns:
            Dict with comment details, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.add_comment(document_id, content, quoted_text)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_docs_export_content(
        document_id: str,
        format: str = "pdf",
    ) -> dict:
        """
        Export the document to different formats (PDF, DOCX, TXT).

        Args:
            document_id: The ID of the Google Docs document
            format: Export format - "pdf", "docx", "txt", "html", "odt", "rtf", "epub"

        Returns:
            Dict with base64-encoded content and metadata, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        mime_types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "html": "text/html",
            "odt": "application/vnd.oasis.opendocument.text",
            "rtf": "application/rtf",
            "epub": "application/epub+zip",
        }
        mime_type = mime_types.get(format.lower(), "application/pdf")

        try:
            return client.export_document(document_id, mime_type)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
