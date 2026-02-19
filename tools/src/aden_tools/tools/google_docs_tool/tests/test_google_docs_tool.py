"""
Tests for Google Docs Tool.

These tests use mocked HTTP responses to verify the tool's behavior
without requiring actual Google API credentials.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_docs_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with Google Docs tools registered."""
    server = FastMCP("test")
    register_tools(server)
    return server


@pytest.fixture
def mcp_with_credentials():
    """Create a FastMCP instance with mocked credentials."""
    server = FastMCP("test")
    mock_credentials = MagicMock()
    mock_credentials.get.return_value = "test-access-token"
    register_tools(server, credentials=mock_credentials)
    return server


def get_tool_fn(mcp, tool_name: str):
    """Helper to get a tool function from the MCP server."""
    return mcp._tool_manager._tools[tool_name].fn


class TestGoogleDocsCreateDocument:
    """Tests for google_docs_create_document tool."""

    def test_no_credentials_returns_error(self, mcp):
        """Test that missing credentials returns a helpful error."""
        with patch.dict("os.environ", {}, clear=True):
            tool_fn = get_tool_fn(mcp, "google_docs_create_document")
            result = tool_fn(title="Test Document")
            assert "error" in result
            assert "not configured" in result["error"]
            assert "help" in result

    def test_service_account_json_without_access_token_is_not_used(self, mcp):
        """Test that service account JSON alone is not treated as an access token."""
        with patch.dict(
            "os.environ", {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"type":"service_account"}'}
        ):
            tool_fn = get_tool_fn(mcp, "google_docs_create_document")
            result = tool_fn(title="Test Document")
            assert "error" in result
            assert "not configured" in result["error"]

    @patch("httpx.post")
    def test_create_document_success(self, mock_post, mcp_with_credentials):
        """Test successful document creation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "documentId": "doc123",
            "title": "Test Document",
        }
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_create_document")
        result = tool_fn(title="Test Document")

        assert result["document_id"] == "doc123"
        assert result["title"] == "Test Document"
        assert "document_url" in result
        assert "doc123" in result["document_url"]

    @patch("httpx.post")
    def test_create_document_unauthorized(self, mock_post, mcp_with_credentials):
        """Test handling of 401 unauthorized response."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_create_document")
        result = tool_fn(title="Test Document")

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()


class TestGoogleDocsGetDocument:
    """Tests for google_docs_get_document tool."""

    @patch("httpx.get")
    def test_get_document_success(self, mock_get, mcp_with_credentials):
        """Test successful document retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "documentId": "doc123",
            "title": "Test Document",
            "body": {"content": []},
        }
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_get_document")
        result = tool_fn(document_id="doc123")

        assert result["documentId"] == "doc123"
        assert result["title"] == "Test Document"

    @patch("httpx.get")
    def test_get_document_not_found(self, mock_get, mcp_with_credentials):
        """Test handling of 404 not found response."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_get_document")
        result = tool_fn(document_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestGoogleDocsReplaceAllText:
    """Tests for google_docs_replace_all_text tool."""

    @patch("httpx.post")
    def test_replace_all_text_success(self, mock_post, mcp_with_credentials):
        """Test successful find and replace."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "replies": [{"replaceAllText": {"occurrencesChanged": 3}}]
        }
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_replace_all_text")
        result = tool_fn(
            document_id="doc123",
            find_text="{{placeholder}}",
            replace_text="actual value",
        )

        assert result["occurrences_replaced"] == 3
        assert result["find_text"] == "{{placeholder}}"
        assert result["replace_text"] == "actual value"


class TestGoogleDocsInsertText:
    """Tests for google_docs_insert_text tool."""

    @patch("httpx.post")
    @patch("httpx.get")
    def test_insert_text_at_end(self, mock_get, mock_post, mcp_with_credentials):
        """Test inserting text at the end of document."""
        # Mock get document for finding end index
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {"body": {"content": [{"endIndex": 100}]}}
        mock_get.return_value = mock_get_response

        # Mock batch update
        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_post_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_text")
        result = tool_fn(document_id="doc123", text="Hello, World!")

        assert "error" not in result

    @patch("httpx.post")
    def test_insert_text_at_index(self, mock_post, mcp_with_credentials):
        """Test inserting text at a specific index."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_text")
        result = tool_fn(document_id="doc123", text="Inserted", index=10)

        assert "error" not in result


class TestGoogleDocsFormatText:
    """Tests for google_docs_format_text tool."""

    @patch("httpx.post")
    def test_format_text_bold(self, mock_post, mcp_with_credentials):
        """Test applying bold formatting."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_format_text")
        result = tool_fn(
            document_id="doc123",
            start_index=1,
            end_index=10,
            bold=True,
        )

        assert "error" not in result

    def test_format_text_no_options(self, mcp_with_credentials):
        """Test error when no formatting options specified."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_format_text")
        result = tool_fn(
            document_id="doc123",
            start_index=1,
            end_index=10,
        )

        assert "error" in result
        assert "No formatting options" in result["error"]


class TestGoogleDocsBatchUpdate:
    """Tests for google_docs_batch_update tool."""

    @patch("httpx.post")
    def test_batch_update_success(self, mock_post, mcp_with_credentials):
        """Test successful batch update."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": [{}, {}]}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_batch_update")
        requests = json.dumps(
            [
                {"insertText": {"location": {"index": 1}, "text": "Hello"}},
                {"insertText": {"location": {"index": 6}, "text": " World"}},
            ]
        )
        result = tool_fn(document_id="doc123", requests_json=requests)

        assert "error" not in result

    def test_batch_update_invalid_json(self, mcp_with_credentials):
        """Test error handling for invalid JSON."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_batch_update")
        result = tool_fn(document_id="doc123", requests_json="not valid json")

        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_batch_update_not_array(self, mcp_with_credentials):
        """Test error handling when JSON is not an array."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_batch_update")
        result = tool_fn(document_id="doc123", requests_json='{"not": "array"}')

        assert "error" in result
        assert "array" in result["error"].lower()


class TestGoogleDocsExport:
    """Tests for google_docs_export_content tool."""

    @patch("httpx.get")
    def test_export_to_pdf(self, mock_get, mcp_with_credentials):
        """Test exporting document to PDF."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"PDF content here"
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_export_content")
        result = tool_fn(document_id="doc123", format="pdf")

        assert result["document_id"] == "doc123"
        assert result["mime_type"] == "application/pdf"
        assert "content_base64" in result
        assert result["size_bytes"] == len(b"PDF content here")

    @patch("httpx.get")
    def test_export_to_docx(self, mock_get, mcp_with_credentials):
        """Test exporting document to DOCX."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"DOCX content"
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_export_content")
        result = tool_fn(document_id="doc123", format="docx")

        assert "application/vnd.openxmlformats" in result["mime_type"]


class TestGoogleDocsCreateList:
    """Tests for google_docs_create_list tool."""

    @patch("httpx.post")
    def test_create_bullet_list(self, mock_post, mcp_with_credentials):
        """Test creating a bullet list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_create_list")
        result = tool_fn(
            document_id="doc123",
            start_index=1,
            end_index=50,
            list_type="bullet",
        )

        assert "error" not in result

    @patch("httpx.post")
    def test_create_numbered_list(self, mock_post, mcp_with_credentials):
        """Test creating a numbered list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_create_list")
        result = tool_fn(
            document_id="doc123",
            start_index=1,
            end_index=50,
            list_type="numbered",
        )

        assert "error" not in result


class TestGoogleDocsAddComment:
    """Tests for google_docs_add_comment tool."""

    @patch("httpx.post")
    def test_add_comment_success(self, mock_post, mcp_with_credentials):
        """Test adding a comment to a document."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "comment123",
            "content": "This needs review",
        }
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_add_comment")
        result = tool_fn(
            document_id="doc123",
            content="This needs review",
        )

        assert result["id"] == "comment123"
        assert result["content"] == "This needs review"


class TestImageUriValidation:
    """Tests for image URI validation."""

    @patch("httpx.post")
    def test_insert_image_valid_https_uri(self, mock_post, mcp_with_credentials):
        """Test that valid HTTPS URIs are accepted."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_image")
        result = tool_fn(
            document_id="doc123",
            image_uri="https://example.com/image.png",
            index=1,
        )

        assert "error" not in result

    def test_insert_image_empty_uri(self, mcp_with_credentials):
        """Test that empty URI returns an error."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_image")
        result = tool_fn(
            document_id="doc123",
            image_uri="",
            index=1,
        )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_insert_image_invalid_scheme(self, mcp_with_credentials):
        """Test that non-http(s) schemes are rejected."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_image")
        result = tool_fn(
            document_id="doc123",
            image_uri="ftp://example.com/image.png",
            index=1,
        )

        assert "error" in result
        assert "scheme" in result["error"].lower()

    def test_insert_image_missing_scheme(self, mcp_with_credentials):
        """Test that URIs without scheme are rejected."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_image")
        result = tool_fn(
            document_id="doc123",
            image_uri="example.com/image.png",
            index=1,
        )

        assert "error" in result
        assert "scheme" in result["error"].lower() or "format" in result["error"].lower()

    def test_insert_image_javascript_uri_rejected(self, mcp_with_credentials):
        """Test that javascript: URIs are rejected."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_insert_image")
        result = tool_fn(
            document_id="doc123",
            image_uri="javascript:alert('xss')",
            index=1,
        )

        assert "error" in result


class TestReplaceAllTextValidation:
    """Tests for replace_all_text validation."""

    def test_replace_all_text_empty_find_text(self, mcp_with_credentials):
        """Test that empty find_text returns an error."""
        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_replace_all_text")
        result = tool_fn(
            document_id="doc123",
            find_text="",
            replace_text="replacement",
        )

        assert "error" in result
        assert "empty" in result["error"].lower()


class TestServiceAccountTokenExchange:
    """Tests for service account JWT token exchange."""

    @patch("httpx.post")
    @patch.dict(
        "os.environ",
        {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"access_token": "pre-exchanged-token"}'},
    )
    def test_fallback_to_pre_exchanged_token(self, mock_post):
        """Test that pre-exchanged tokens in JSON are used as fallback."""
        server = FastMCP("test")
        register_tools(server)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "documentId": "doc123",
            "title": "Test",
        }
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(server, "google_docs_create_document")
        result = tool_fn(title="Test")

        # Should use the pre-exchanged token and make the API call
        assert "error" not in result or "not configured" not in result.get("error", "")


class TestGoogleDocsListComments:
    """Tests for google_docs_list_comments tool."""

    @patch("httpx.get")
    def test_list_comments_success(self, mock_get, mcp_with_credentials):
        """Test retrieving comments with pagination token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "comments": [{"id": "comment123", "content": "Looks good"}],
            "nextPageToken": "next-token",
        }
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_list_comments")
        result = tool_fn(document_id="doc123", page_size=10)

        assert result["document_id"] == "doc123"
        assert len(result["comments"]) == 1
        assert result["comments"][0]["id"] == "comment123"
        assert result["next_page_token"] == "next-token"

    @patch("httpx.get")
    def test_list_comments_not_found(self, mock_get, mcp_with_credentials):
        """Test handling a missing document for comment retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_docs_list_comments")
        result = tool_fn(document_id="does-not-exist")

        assert "error" in result
        assert "not found" in result["error"].lower()
