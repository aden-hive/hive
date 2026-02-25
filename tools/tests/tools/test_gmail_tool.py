"""Tests for Gmail inbox management tools (FastMCP)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.gmail_tool import register_tools

HTTPX_MODULE = "aden_tools.tools.gmail_tool.gmail_tool.httpx.request"


@pytest.fixture
def gmail_tools(mcp: FastMCP):
    """Register Gmail tools and return a dict of tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def list_fn(gmail_tools):
    return gmail_tools["gmail_list_messages"]


@pytest.fixture
def get_fn(gmail_tools):
    return gmail_tools["gmail_get_message"]


@pytest.fixture
def trash_fn(gmail_tools):
    return gmail_tools["gmail_trash_message"]


@pytest.fixture
def modify_fn(gmail_tools):
    return gmail_tools["gmail_modify_message"]


@pytest.fixture
def batch_fn(gmail_tools):
    return gmail_tools["gmail_batch_modify_messages"]


@pytest.fixture
def list_labels_fn(gmail_tools):
    return gmail_tools["gmail_list_labels"]


@pytest.fixture
def create_label_fn(gmail_tools):
    return gmail_tools["gmail_create_label"]


def _mock_response(
    status_code: int = 200, json_data: dict | None = None, text: str = ""
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Credential handling (shared across all tools)
# ---------------------------------------------------------------------------


class TestCredentials:
    """All Gmail tools require GOOGLE_ACCESS_TOKEN."""

    def test_list_no_credentials(self, list_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = list_fn()
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]
        assert "help" in result

    def test_get_no_credentials(self, get_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = get_fn(message_id="abc")
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]

    def test_trash_no_credentials(self, trash_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = trash_fn(message_id="abc")
        assert "error" in result

    def test_modify_no_credentials(self, modify_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = modify_fn(message_id="abc", add_labels=["STARRED"])
        assert "error" in result

    def test_batch_no_credentials(self, batch_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = batch_fn(message_ids=["abc"], add_labels=["STARRED"])
        assert "error" in result

    def test_list_labels_no_credentials(self, list_labels_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = list_labels_fn()
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]

    def test_create_label_no_credentials(self, create_label_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = create_label_fn(name="Test")
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]


# ---------------------------------------------------------------------------
# gmail_list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_list_success(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {
                "messages": [{"id": "msg1", "threadId": "t1"}, {"id": "msg2", "threadId": "t2"}],
                "resultSizeEstimate": 2,
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = list_fn(query="is:unread", max_results=10)

        assert result["messages"] == [
            {"id": "msg1", "threadId": "t1"},
            {"id": "msg2", "threadId": "t2"},
        ]
        assert result["result_size_estimate"] == 2
        # Verify correct API call
        call_args = mock_req.call_args
        assert call_args[0][0] == "GET"
        assert "messages" in call_args[0][1]
        assert call_args[1]["params"]["q"] == "is:unread"
        assert call_args[1]["params"]["maxResults"] == 10

    def test_list_empty_inbox(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {"resultSizeEstimate": 0})
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = list_fn()

        assert result["messages"] == []
        assert result["result_size_estimate"] == 0

    def test_list_with_page_token(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {
                "messages": [{"id": "msg3", "threadId": "t3"}],
                "nextPageToken": "page2",
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = list_fn(page_token="page1")

        assert result["next_page_token"] == "page2"
        assert mock_req.call_args[1]["params"]["pageToken"] == "page1"

    def test_list_max_results_clamped(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {"messages": []})
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            list_fn(max_results=999)

        assert mock_req.call_args[1]["params"]["maxResults"] == 500

    def test_list_token_expired(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "expired")
        mock_resp = _mock_response(401)
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = list_fn()

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
        assert "help" in result

    def test_list_network_error(self, list_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        with patch(HTTPX_MODULE, side_effect=httpx.HTTPError("connection refused")):
            result = list_fn()

        assert "error" in result
        assert "Request failed" in result["error"]


# ---------------------------------------------------------------------------
# gmail_get_message
# ---------------------------------------------------------------------------


class TestGetMessage:
    def test_get_metadata(self, get_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {
                "id": "msg1",
                "threadId": "t1",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": "Hey there...",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hello"},
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "To", "value": "bob@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2026 00:00:00 +0000"},
                    ],
                },
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = get_fn(message_id="msg1")

        assert result["id"] == "msg1"
        assert result["labels"] == ["INBOX", "UNREAD"]
        assert result["snippet"] == "Hey there..."
        assert result["subject"] == "Hello"
        assert result["from"] == "alice@example.com"

    def test_get_full_with_body(self, get_fn, monkeypatch):
        import base64

        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        body_b64 = base64.urlsafe_b64encode(b"Hello world").decode()
        mock_resp = _mock_response(
            200,
            {
                "id": "msg2",
                "threadId": "t2",
                "labelIds": ["INBOX"],
                "snippet": "Hello...",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Test"}],
                    "body": {"data": body_b64},
                },
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = get_fn(message_id="msg2", format="full")

        assert result["body"] == "Hello world"

    def test_get_multipart_body(self, get_fn, monkeypatch):
        import base64

        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        plain_b64 = base64.urlsafe_b64encode(b"Plain text body").decode()
        mock_resp = _mock_response(
            200,
            {
                "id": "msg3",
                "threadId": "t3",
                "labelIds": [],
                "snippet": "Plain...",
                "payload": {
                    "headers": [],
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": plain_b64}},
                        {"mimeType": "text/html", "body": {"data": "ignored"}},
                    ],
                },
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = get_fn(message_id="msg3", format="full")

        assert result["body"] == "Plain text body"

    def test_get_empty_message_id(self, get_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = get_fn(message_id="")
        assert "error" in result
        assert "message_id is required" in result["error"]

    def test_get_not_found(self, get_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(404)
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = get_fn(message_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# gmail_trash_message
# ---------------------------------------------------------------------------


class TestTrashMessage:
    def test_trash_success(self, trash_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {"id": "msg1", "labelIds": ["TRASH"]})
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = trash_fn(message_id="msg1")

        assert result["success"] is True
        assert result["message_id"] == "msg1"
        call_args = mock_req.call_args
        assert call_args[0][0] == "POST"
        assert "messages/msg1/trash" in call_args[0][1]

    def test_trash_empty_id(self, trash_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = trash_fn(message_id="")
        assert "error" in result

    def test_trash_not_found(self, trash_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(404)
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = trash_fn(message_id="nonexistent")

        assert "error" in result


# ---------------------------------------------------------------------------
# gmail_modify_message
# ---------------------------------------------------------------------------


class TestModifyMessage:
    def test_star_message(self, modify_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {"id": "msg1", "labelIds": ["INBOX", "STARRED"]})
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = modify_fn(message_id="msg1", add_labels=["STARRED"])

        assert result["success"] is True
        assert result["labels"] == ["INBOX", "STARRED"]
        body = mock_req.call_args[1]["json"]
        assert body["addLabelIds"] == ["STARRED"]
        assert "removeLabelIds" not in body

    def test_mark_as_read(self, modify_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {"id": "msg1", "labelIds": ["INBOX"]})
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = modify_fn(message_id="msg1", remove_labels=["UNREAD"])

        assert result["success"] is True
        body = mock_req.call_args[1]["json"]
        assert body["removeLabelIds"] == ["UNREAD"]

    def test_modify_no_labels_returns_error(self, modify_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = modify_fn(message_id="msg1")
        assert "error" in result
        assert "add_labels or remove_labels" in result["error"]

    def test_modify_empty_id(self, modify_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = modify_fn(message_id="", add_labels=["STARRED"])
        assert "error" in result

    def test_modify_api_error(self, modify_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(403, text="Insufficient permissions")
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = modify_fn(message_id="msg1", add_labels=["STARRED"])

        assert "error" in result
        assert "403" in result["error"]


# ---------------------------------------------------------------------------
# gmail_batch_modify_messages
# ---------------------------------------------------------------------------


class TestBatchModifyMessages:
    def test_batch_success(self, batch_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(204)
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = batch_fn(
                message_ids=["msg1", "msg2", "msg3"],
                remove_labels=["UNREAD"],
            )

        assert result["success"] is True
        assert result["count"] == 3
        body = mock_req.call_args[1]["json"]
        assert body["ids"] == ["msg1", "msg2", "msg3"]
        assert body["removeLabelIds"] == ["UNREAD"]

    def test_batch_empty_ids_returns_error(self, batch_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = batch_fn(message_ids=[], add_labels=["STARRED"])
        assert "error" in result

    def test_batch_no_labels_returns_error(self, batch_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = batch_fn(message_ids=["msg1"])
        assert "error" in result

    def test_batch_api_error(self, batch_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(400, text="Invalid label")
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = batch_fn(message_ids=["msg1"], add_labels=["FAKE_LABEL"])

        assert "error" in result


# ---------------------------------------------------------------------------
# gmail_list_labels
# ---------------------------------------------------------------------------


class TestListLabels:
    def test_list_labels_success(self, list_labels_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {"id": "Label_1", "name": "MyLabel", "type": "user"},
                ],
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = list_labels_fn()

        assert len(result["labels"]) == 2
        assert result["labels"][0]["id"] == "INBOX"
        assert result["labels"][1]["name"] == "MyLabel"
        call_args = mock_req.call_args
        assert call_args[0][0] == "GET"
        assert "labels" in call_args[0][1]

    def test_list_labels_empty(self, list_labels_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(200, {})
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = list_labels_fn()

        assert result["labels"] == []

    def test_list_labels_token_expired(self, list_labels_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "expired")
        mock_resp = _mock_response(401)
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = list_labels_fn()

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()

    def test_list_labels_network_error(self, list_labels_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        with patch(HTTPX_MODULE, side_effect=httpx.HTTPError("connection refused")):
            result = list_labels_fn()

        assert "error" in result
        assert "Request failed" in result["error"]


# ---------------------------------------------------------------------------
# gmail_create_label
# ---------------------------------------------------------------------------


class TestCreateLabel:
    def test_create_label_success(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {
                "id": "Label_42",
                "name": "Agent/Important",
                "type": "user",
            },
        )
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = create_label_fn(name="Agent/Important")

        assert result["success"] is True
        assert result["id"] == "Label_42"
        assert result["name"] == "Agent/Important"
        assert result["type"] == "user"
        body = mock_req.call_args[1]["json"]
        assert body["name"] == "Agent/Important"
        assert body["labelListVisibility"] == "labelShow"
        assert body["messageListVisibility"] == "show"

    def test_create_label_custom_visibility(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(
            200,
            {"id": "Label_43", "name": "Hidden", "type": "user"},
        )
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = create_label_fn(
                name="Hidden",
                label_list_visibility="labelHide",
                message_list_visibility="hide",
            )

        assert result["success"] is True
        body = mock_req.call_args[1]["json"]
        assert body["labelListVisibility"] == "labelHide"
        assert body["messageListVisibility"] == "hide"

    def test_create_label_empty_name(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = create_label_fn(name="")
        assert "error" in result
        assert "Label name is required" in result["error"]

    def test_create_label_whitespace_name(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        result = create_label_fn(name="   ")
        assert "error" in result
        assert "Label name is required" in result["error"]

    def test_create_label_api_error(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        mock_resp = _mock_response(409, text="Label name exists")
        with patch(HTTPX_MODULE, return_value=mock_resp):
            result = create_label_fn(name="Duplicate")

        assert "error" in result
        assert "409" in result["error"]

    def test_create_label_network_error(self, create_label_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test_token")
        with patch(HTTPX_MODULE, side_effect=httpx.HTTPError("timeout")):
            result = create_label_fn(name="Test")

        assert "error" in result
        assert "Request failed" in result["error"]
