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


# ---------------------------------------------------------------------------
# gmail_create_draft
# ---------------------------------------------------------------------------


@pytest.fixture
def create_draft_fn(gmail_tools):
    return gmail_tools["gmail_create_draft"]


def _orig_message_response(
    thread_id: str = "thread123",
    message_id_header: str = "<orig-msg-id@mail.gmail.com>",
    subject: str = "Hello there",
    from_addr: str = "sender@example.com",
    body_html: str = "<p>Original body</p>",
) -> MagicMock:
    """Mock response for fetching an original message (format=full)."""
    import base64

    encoded_body = base64.urlsafe_b64encode(body_html.encode()).decode()
    return _mock_response(
        200,
        {
            "threadId": thread_id,
            "payload": {
                "mimeType": "text/html",
                "headers": [
                    {"name": "Message-ID", "value": message_id_header},
                    {"name": "Subject", "value": subject},
                    {"name": "From", "value": from_addr},
                    {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                ],
                "body": {"data": encoded_body},
                "parts": [],
            },
        },
    )


class TestGmailCreateDraft:
    """Tests for gmail_create_draft tool."""

    # -- new draft (no reply) -------------------------------------------------

    def test_no_credentials(self, create_draft_fn, monkeypatch):
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        result = create_draft_fn(html="<p>Hi</p>", to="a@b.com", subject="Hey")
        assert "error" in result
        assert "Gmail credentials not configured" in result["error"]

    def test_missing_to(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        result = create_draft_fn(html="<p>Hi</p>", subject="Hey")
        assert "error" in result
        assert "to" in result["error"].lower()

    def test_missing_subject(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        result = create_draft_fn(html="<p>Hi</p>", to="a@b.com")
        assert "error" in result
        assert "subject" in result["error"].lower()

    def test_missing_html(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        result = create_draft_fn(html="", to="a@b.com", subject="Hey")
        assert "error" in result
        assert "html" in result["error"].lower()

    def test_new_draft_happy_path(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        mock_resp = _mock_response(200, {"id": "draft1", "message": {"id": "msg1"}})
        with patch(HTTPX_MODULE, return_value=mock_resp) as mock_req:
            result = create_draft_fn(html="<p>Hi</p>", to="a@b.com", subject="Hey")

        assert result["success"] is True
        assert result["draft_id"] == "draft1"
        assert result["message_id"] == "msg1"
        assert "thread_id" not in result
        # threadId should NOT be in the API body
        body = mock_req.call_args[1]["json"]
        assert "threadId" not in body["message"]

    # -- reply draft ----------------------------------------------------------

    def test_reply_draft_happy_path(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _orig_message_response()
        draft_resp = _mock_response(200, {"id": "draft2", "message": {"id": "msg2"}})

        calls = [orig_resp, draft_resp]
        with patch(HTTPX_MODULE, side_effect=calls) as mock_req:
            result = create_draft_fn(
                html="<p>Reply</p>",
                reply_to_message_id="origmsg123",
            )

        assert result["success"] is True
        assert result["draft_id"] == "draft2"
        assert result["thread_id"] == "thread123"

        # Verify draft API call has threadId
        draft_call = mock_req.call_args_list[1]
        body = draft_call[1]["json"]
        assert body["message"]["threadId"] == "thread123"

        # Verify MIME headers and quoted body
        import base64
        import email

        raw = base64.urlsafe_b64decode(body["message"]["raw"])
        mime = email.message_from_bytes(raw)
        assert mime["In-Reply-To"] == "<orig-msg-id@mail.gmail.com>"
        assert mime["References"] == "<orig-msg-id@mail.gmail.com>"
        assert mime["To"] == "sender@example.com"
        assert mime["Subject"] == "Re: Hello there"

        # Verify quoted original body is embedded
        mime_body = mime.get_payload(decode=True)
        if mime_body is None:
            # multipart — find the html part
            for part in mime.walk():
                if part.get_content_type() == "text/html":
                    mime_body = part.get_payload(decode=True)
                    break
        decoded_body = mime_body.decode("utf-8") if mime_body else ""
        assert "<p>Reply</p>" in decoded_body
        assert "gmail_quote" in decoded_body
        assert "<p>Original body</p>" in decoded_body
        assert "blockquote" in decoded_body

    def test_reply_draft_subject_already_re(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _orig_message_response(subject="Re: Hello there")
        draft_resp = _mock_response(200, {"id": "d3", "message": {"id": "m3"}})

        with patch(HTTPX_MODULE, side_effect=[orig_resp, draft_resp]):
            result = create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")

        # Extract subject from result — it should not be "Re: Re: Hello there"
        assert result["success"] is True
        # Check via MIME is covered by test_reply_draft_subject_no_double_re below.

    def test_reply_draft_subject_no_double_re(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _orig_message_response(subject="Re: Hello there")
        draft_resp = _mock_response(200, {"id": "d4", "message": {"id": "m4"}})

        with patch(HTTPX_MODULE, side_effect=[orig_resp, draft_resp]) as mock_req:
            create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")

        import base64
        import email

        body = mock_req.call_args_list[1][1]["json"]
        raw = base64.urlsafe_b64decode(body["message"]["raw"])
        mime = email.message_from_bytes(raw)
        assert mime["Subject"] == "Re: Hello there"

    def test_reply_draft_fetch_401(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _mock_response(401)
        with patch(HTTPX_MODULE, return_value=orig_resp):
            result = create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")
        assert "error" in result
        assert "token" in result["error"].lower()

    def test_reply_draft_fetch_404(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _mock_response(404)
        with patch(HTTPX_MODULE, return_value=orig_resp):
            result = create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")
        assert "error" in result

    def test_reply_draft_network_error_on_fetch(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        with patch(HTTPX_MODULE, side_effect=httpx.HTTPError("timeout")):
            result = create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")
        assert "error" in result
        assert "fetch" in result["error"].lower()

    def test_reply_draft_api_error_on_create(self, create_draft_fn, monkeypatch):
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "tok")
        orig_resp = _orig_message_response()
        draft_resp = _mock_response(500, text="internal error")
        with patch(HTTPX_MODULE, side_effect=[orig_resp, draft_resp]):
            result = create_draft_fn(html="<p>x</p>", reply_to_message_id="origmsg")
        assert "error" in result
