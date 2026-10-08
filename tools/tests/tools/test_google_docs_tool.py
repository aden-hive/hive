"""Tests for Google Docs tool with FastMCP.

Covers:
- Credential handling (credential store, env var, service account, missing)
- _GoogleDocsClient methods (create, get, insert, replace, image, format, list, batch, export)
- HTTP error handling (401, 403, 404, 429, 500, timeout)
- All MCP tool functions via register_tools
- Input validation (image URI, JSON parsing, list types, format types)
- Helper functions (_validate_image_uri, _get_document_end_index)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_docs_tool.google_docs_tool import (
    GOOGLE_DOCS_API_BASE,
    _get_document_end_index,
    _GoogleDocsClient,
    _validate_image_uri,
    register_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def client():
    """Create a _GoogleDocsClient with a test token."""
    return _GoogleDocsClient("test-token")


def _register(mcp, credentials=None):
    """Helper to register tools and return the tool lookup dict."""
    register_tools(mcp, credentials=credentials)
    return mcp._tool_manager._tools


def _tool_fn(mcp, name, credentials=None):
    """Register tools and return a single tool function by name."""
    tools = _register(mcp, credentials)
    return tools[name].fn


def _mock_response(status_code=200, json_data=None, text="", content=b""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestValidateImageUri:
    """Tests for _validate_image_uri."""

    def test_valid_https_url(self):
        assert _validate_image_uri("https://example.com/image.png") is None

    def test_valid_http_url(self):
        assert _validate_image_uri("http://example.com/image.jpg") is None

    def test_empty_uri(self):
        result = _validate_image_uri("")
        assert result is not None
        assert "error" in result

    def test_whitespace_uri(self):
        result = _validate_image_uri("   ")
        assert result is not None
        assert "error" in result

    def test_missing_scheme(self):
        result = _validate_image_uri("example.com/image.png")
        assert result is not None
        assert "missing scheme" in result["error"]

    def test_disallowed_scheme_ftp(self):
        result = _validate_image_uri("ftp://example.com/image.png")
        assert result is not None
        assert "Only" in result["error"]

    def test_disallowed_scheme_javascript(self):
        result = _validate_image_uri("javascript:alert(1)")
        assert result is not None
        assert "error" in result

    def test_missing_domain(self):
        result = _validate_image_uri("https://")
        assert result is not None
        assert "error" in result


class TestGetDocumentEndIndex:
    """Tests for _get_document_end_index."""

    def test_returns_end_index_minus_one(self):
        doc = {
            "body": {
                "content": [
                    {"startIndex": 1, "endIndex": 50},
                ]
            }
        }
        assert _get_document_end_index(doc) == 49

    def test_empty_content_returns_one(self):
        doc = {"body": {"content": []}}
        assert _get_document_end_index(doc) == 1

    def test_no_body_returns_one(self):
        doc = {}
        assert _get_document_end_index(doc) == 1


# ---------------------------------------------------------------------------
# _GoogleDocsClient unit tests
# ---------------------------------------------------------------------------


class TestGoogleDocsClientHeaders:
    def test_headers_contain_bearer_token(self, client):
        headers = client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"


class TestGoogleDocsClientHandleResponse:
    @pytest.mark.parametrize(
        "status_code,expected_substr",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_known_error_codes(self, client, status_code, expected_substr):
        resp = _mock_response(status_code=status_code)
        result = client._handle_response(resp)
        assert "error" in result
        assert expected_substr in result["error"]

    def test_generic_error_with_nested_message(self, client):
        resp = _mock_response(
            status_code=400,
            json_data={"error": {"message": "Invalid request"}},
        )
        result = client._handle_response(resp)
        assert "Invalid request" in result["error"]

    def test_success_returns_json(self, client):
        resp = _mock_response(200, {"documentId": "doc-1"})
        assert client._handle_response(resp) == {"documentId": "doc-1"}


class TestGoogleDocsClientCreateDocument:
    def test_posts_title(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"documentId": "doc-1", "title": "My Doc"})
            result = client.create_document("My Doc")
            body = mock_post.call_args.kwargs["json"]
            assert body == {"title": "My Doc"}
            assert result["documentId"] == "doc-1"


class TestGoogleDocsClientGetDocument:
    def test_gets_correct_url(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"documentId": "doc-1"})
            client.get_document("doc-1")
            args, _ = mock_get.call_args
            assert args[0] == f"{GOOGLE_DOCS_API_BASE}/documents/doc-1"


class TestGoogleDocsClientBatchUpdate:
    def test_batch_update_sends_requests(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            requests = [{"insertText": {"text": "hello", "location": {"index": 1}}}]
            client.batch_update("doc-1", requests)
            body = mock_post.call_args.kwargs["json"]
            assert body["requests"] == requests


class TestGoogleDocsClientInsertText:
    def test_insert_at_index(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.insert_text("doc-1", "Hello", index=5)
            body = mock_post.call_args.kwargs["json"]
            req = body["requests"][0]["insertText"]
            assert req["text"] == "Hello"
            assert req["location"]["index"] == 5

    def test_insert_at_end_fetches_doc(self, client):
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = _mock_response(
                200,
                {"body": {"content": [{"startIndex": 1, "endIndex": 20}]}},
            )
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.insert_text("doc-1", "Appended text")
            # Should have fetched doc to determine end index
            mock_get.assert_called_once()


class TestGoogleDocsClientReplaceAllText:
    def test_replace_sends_correct_request(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.replace_all_text("doc-1", "{{NAME}}", "Alice")
            body = mock_post.call_args.kwargs["json"]
            req = body["requests"][0]["replaceAllText"]
            assert req["containsText"]["text"] == "{{NAME}}"
            assert req["replaceText"] == "Alice"

    def test_empty_find_text_returns_error(self, client):
        result = client.replace_all_text("doc-1", "", "Alice")
        assert "error" in result


class TestGoogleDocsClientInsertImage:
    def test_valid_image_insertion(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.insert_image("doc-1", "https://example.com/img.png", index=1)
            body = mock_post.call_args.kwargs["json"]
            req = body["requests"][0]["insertInlineImage"]
            assert req["uri"] == "https://example.com/img.png"

    def test_invalid_uri_returns_error(self, client):
        result = client.insert_image("doc-1", "ftp://bad.com/img.png", index=1)
        assert "error" in result

    def test_image_with_dimensions(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.insert_image(
                "doc-1",
                "https://example.com/img.png",
                index=1,
                width_pt=200.0,
                height_pt=100.0,
            )
            body = mock_post.call_args.kwargs["json"]
            req = body["requests"][0]["insertInlineImage"]
            assert req["objectSize"]["width"]["magnitude"] == 200.0


class TestGoogleDocsClientFormatText:
    def test_bold_formatting(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            client.format_text("doc-1", 1, 10, bold=True)
            body = mock_post.call_args.kwargs["json"]
            req = body["requests"][0]["updateTextStyle"]
            assert req["textStyle"]["bold"] is True
            assert "bold" in req["fields"]

    def test_no_options_returns_error(self, client):
        result = client.format_text("doc-1", 1, 10)
        assert "error" in result
        assert "No formatting" in result["error"]


class TestGoogleDocsClientExportDocument:
    def test_export_pdf(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, content=b"%PDF-1.4 content")
            result = client.export_document("doc-1", "application/pdf")
            assert result["mime_type"] == "application/pdf"
            assert result["size_bytes"] == len(b"%PDF-1.4 content")
            assert "content_base64" in result


class TestGoogleDocsClientComments:
    def test_add_comment(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "comment-1", "content": "Nice work"})
            result = client.add_comment("doc-1", "Nice work")
            assert result["id"] == "comment-1"

    def test_add_comment_with_quoted_text(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "comment-1"})
            client.add_comment("doc-1", "Fix this", quoted_text="typo here")
            body = mock_post.call_args.kwargs["json"]
            assert body["quotedFileContent"]["value"] == "typo here"

    def test_list_comments(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"comments": [{"id": "c1"}], "nextPageToken": "tok2"})
            result = client.list_comments("doc-1", page_size=10)
            assert len(result["comments"]) == 1


# ---------------------------------------------------------------------------
# Credential handling via register_tools
# ---------------------------------------------------------------------------


class TestGoogleDocsCredentials:
    def test_no_credentials_returns_error(self, mcp, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        fn = _tool_fn(mcp, "google_docs_get_document")
        result = fn(document_id="doc-1")
        assert "error" in result
        assert "not configured" in result["error"]

    def test_env_var_credential(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "env-tok")
        fn = _tool_fn(mcp, "google_docs_get_document")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"documentId": "doc-1"})
            fn(document_id="doc-1")
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer env-tok"

    def test_credential_store_used(self, mcp):
        creds = MagicMock()
        creds.get.return_value = "store-tok"
        fn = _tool_fn(mcp, "google_docs_get_document", credentials=creds)
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"documentId": "doc-1"})
            fn(document_id="doc-1")
            creds.get.assert_called_once_with("google")

    def test_credential_store_non_string_raises(self, mcp):
        creds = MagicMock()
        creds.get.return_value = {"key": "value"}
        fn = _tool_fn(mcp, "google_docs_get_document", credentials=creds)
        with pytest.raises(TypeError, match="Expected string"):
            fn(document_id="doc-1")

    def test_credential_store_account_alias(self, mcp):
        creds = MagicMock()
        creds.get_by_alias.return_value = "alias-tok"
        fn = _tool_fn(mcp, "google_docs_get_document", credentials=creds)
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"documentId": "doc-1"})
            fn(document_id="doc-1", account="my-account")
            creds.get_by_alias.assert_called_once_with("google", "my-account")


# ---------------------------------------------------------------------------
# MCP tool function tests — Document Management
# ---------------------------------------------------------------------------


class TestGoogleDocsCreateDocument:
    def test_success_returns_url(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_create_document")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"documentId": "new-doc", "title": "My Doc"})
            result = fn(title="My Doc")
            assert result["document_id"] == "new-doc"
            assert "document_url" in result
            assert "new-doc" in result["document_url"]

    def test_timeout(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_create_document")
        with patch("httpx.post", side_effect=httpx.TimeoutException("t")):
            result = fn(title="Doc")
            assert result == {"error": "Request timed out"}


class TestGoogleDocsGetDocument:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_get_document")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"documentId": "doc-1", "title": "Test"})
            result = fn(document_id="doc-1")
            assert result["documentId"] == "doc-1"


class TestGoogleDocsInsertText:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_insert_text")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(document_id="doc-1", text="Hello", index=1)
            assert "error" not in result


class TestGoogleDocsReplaceAllText:
    def test_success_with_count(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_replace_all_text")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(
                200,
                {"replies": [{"replaceAllText": {"occurrencesChanged": 3}}]},
            )
            result = fn(
                document_id="doc-1",
                find_text="{{NAME}}",
                replace_text="Alice",
            )
            assert result["occurrences_replaced"] == 3


class TestGoogleDocsInsertImage:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_insert_image")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(
                document_id="doc-1",
                image_uri="https://example.com/img.png",
                index=1,
            )
            assert "error" not in result

    def test_invalid_uri(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_insert_image")
        # This gets caught by the client-level validation
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(
                document_id="doc-1",
                image_uri="ftp://bad.com/img.png",
                index=1,
            )
            assert "error" in result


class TestGoogleDocsFormatText:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_format_text")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(
                document_id="doc-1",
                start_index=1,
                end_index=10,
                bold=True,
            )
            assert "error" not in result


class TestGoogleDocsBatchUpdate:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_batch_update")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            requests = [{"insertText": {"text": "Hi", "location": {"index": 1}}}]
            result = fn(
                document_id="doc-1",
                requests_json=json.dumps(requests),
            )
            assert "error" not in result

    def test_invalid_json(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_batch_update")
        result = fn(document_id="doc-1", requests_json="not json")
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_non_array_json(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_batch_update")
        result = fn(document_id="doc-1", requests_json='{"key": "value"}')
        assert "error" in result
        assert "JSON array" in result["error"]


class TestGoogleDocsCreateList:
    def test_bullet_list(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_create_list")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(
                document_id="doc-1",
                start_index=1,
                end_index=20,
                list_type="bullet",
            )
            assert "error" not in result

    def test_numbered_list(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_create_list")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"replies": []})
            result = fn(
                document_id="doc-1",
                start_index=1,
                end_index=20,
                list_type="numbered",
            )
            assert "error" not in result


class TestGoogleDocsAddComment:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_add_comment")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "comment-1", "content": "Fix this"})
            result = fn(document_id="doc-1", content="Fix this")
            assert result["id"] == "comment-1"


class TestGoogleDocsListComments:
    def test_success_returns_structured(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_list_comments")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(
                200,
                {"comments": [{"id": "c1"}], "nextPageToken": "tok2"},
            )
            result = fn(document_id="doc-1")
            assert result["document_id"] == "doc-1"
            assert len(result["comments"]) == 1
            assert result["next_page_token"] == "tok2"


class TestGoogleDocsExportContent:
    def test_export_pdf(self, mcp, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "google_docs_export_content")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, content=b"PDF data here")
            result = fn(document_id="doc-1", format="pdf")
            assert result["mime_type"] == "application/pdf"
            assert "content_base64" in result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all Google Docs tools are registered."""

    EXPECTED_TOOLS = [
        "google_docs_create_document",
        "google_docs_get_document",
        "google_docs_insert_text",
        "google_docs_replace_all_text",
        "google_docs_insert_image",
        "google_docs_format_text",
        "google_docs_batch_update",
        "google_docs_create_list",
        "google_docs_add_comment",
        "google_docs_list_comments",
        "google_docs_export_content",
    ]

    def test_all_tools_registered(self, mcp):
        tools = _register(mcp)
        for name in self.EXPECTED_TOOLS:
            assert name in tools, f"Tool {name} not registered"

    def test_tool_count(self, mcp):
        tools = _register(mcp)
        gdocs_tools = [k for k in tools if k.startswith("google_docs_")]
        assert len(gdocs_tools) == len(self.EXPECTED_TOOLS)
