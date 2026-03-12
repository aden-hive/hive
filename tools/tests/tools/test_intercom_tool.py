"""Tests for Intercom tool with FastMCP.

Covers:
- Credential handling (credential store, env var, missing)
- _IntercomClient methods (search, get, reply, assign, tag, close, create)
- HTTP error handling (401, 403, 404, 429, 500, timeout)
- All MCP tool functions via register_tools
- Input validation (status, assignee_type, limit, role, tag exclusivity)
- Admin ID lazy-fetch via /me
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.intercom_tool.intercom_tool import (
    INTERCOM_API_BASE,
    _IntercomClient,
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
    """Create an _IntercomClient with a test token."""
    return _IntercomClient("test-token")


def _register(mcp, credentials=None):
    """Helper to register tools and return the tool lookup dict."""
    register_tools(mcp, credentials=credentials)
    return mcp._tool_manager._tools


def _tool_fn(mcp, name, credentials=None):
    """Register tools and return a single tool function by name."""
    tools = _register(mcp, credentials)
    return tools[name].fn


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# _IntercomClient unit tests
# ---------------------------------------------------------------------------


class TestIntercomClientHeaders:
    """Verify client sends correct auth and version headers."""

    def test_headers_contain_bearer_token(self, client):
        headers = client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Intercom-Version"] == "2.11"
        assert headers["Content-Type"] == "application/json"


class TestIntercomClientHandleResponse:
    """Verify _handle_response maps HTTP codes to error dicts."""

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

    def test_intercom_error_list_format(self, client):
        resp = _mock_response(
            status_code=422,
            json_data={
                "type": "error.list",
                "errors": [{"message": "Field is required"}],
            },
        )
        result = client._handle_response(resp)
        assert "Field is required" in result["error"]

    def test_generic_error_fallback_to_text(self, client):
        resp = _mock_response(status_code=500, text="Server Error")
        resp.json.side_effect = Exception("not json")
        result = client._handle_response(resp)
        assert "500" in result["error"]

    def test_success_returns_json(self, client):
        resp = _mock_response(200, {"id": "abc"})
        assert client._handle_response(resp) == {"id": "abc"}


class TestIntercomClientAdminId:
    """Tests for lazy admin ID fetching via /me."""

    def test_fetches_admin_id_on_first_call(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "admin-123"})
            result = client._get_admin_id()
            assert result == "admin-123"
            mock_get.assert_called_once()
            assert INTERCOM_API_BASE + "/me" in mock_get.call_args[0][0]

    def test_caches_admin_id(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "admin-123"})
            client._get_admin_id()
            client._get_admin_id()
            # Only called once due to caching
            assert mock_get.call_count == 1

    def test_returns_error_on_failure(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(401)
            result = client._get_admin_id()
            assert isinstance(result, dict)
            assert "error" in result


class TestIntercomClientSearchConversations:
    def test_posts_to_correct_url(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"conversations": []})
            client.search_conversations({"field": "state", "operator": "=", "value": "open"})
            args, _ = mock_post.call_args
            assert args[0] == f"{INTERCOM_API_BASE}/conversations/search"

    def test_clamps_limit(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"conversations": []})
            client.search_conversations({}, limit=999)
            body = mock_post.call_args.kwargs["json"]
            assert body["pagination"]["per_page"] == 150


class TestIntercomClientGetConversation:
    def test_url_and_plaintext_param(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "conv-1"})
            client.get_conversation("conv-1")
            args, kwargs = mock_get.call_args
            assert "/conversations/conv-1" in args[0]
            assert kwargs["params"]["display_as"] == "plaintext"


class TestIntercomClientReplyToConversation:
    def test_reply_sends_admin_id(self, client):
        client._admin_id = "admin-1"
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"type": "conversation_part"})
            client.reply_to_conversation("conv-1", body="Hello", message_type="comment")
            body = mock_post.call_args.kwargs["json"]
            assert body["admin_id"] == "admin-1"
            assert body["message_type"] == "comment"
            assert body["body"] == "Hello"


class TestIntercomClientCreateContact:
    def test_creates_with_role_and_email(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "contact-1", "role": "user"})
            client.create_contact(role="user", email="test@example.com")
            body = mock_post.call_args.kwargs["json"]
            assert body["role"] == "user"
            assert body["email"] == "test@example.com"

    def test_omits_none_fields(self, client):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "contact-1"})
            client.create_contact(role="lead")
            body = mock_post.call_args.kwargs["json"]
            assert "email" not in body
            assert "name" not in body


class TestIntercomClientListConversations:
    def test_passes_pagination_params(self, client):
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"conversations": []})
            client.list_conversations(limit=10, starting_after="cursor-abc")
            params = mock_get.call_args.kwargs["params"]
            assert params["per_page"] == 10
            assert params["starting_after"] == "cursor-abc"


# ---------------------------------------------------------------------------
# Credential handling via register_tools
# ---------------------------------------------------------------------------


class TestIntercomCredentials:
    """Tests for credential resolution in MCP tool functions."""

    def test_no_credentials_returns_error(self, mcp, monkeypatch):
        monkeypatch.delenv("INTERCOM_ACCESS_TOKEN", raising=False)
        fn = _tool_fn(mcp, "intercom_search_conversations")
        result = fn()
        assert "error" in result
        assert "not configured" in result["error"]

    def test_env_var_credential(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "env-tok")
        fn = _tool_fn(mcp, "intercom_list_teams")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"teams": []})
            fn()
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer env-tok"

    def test_credential_store_used(self, mcp):
        creds = MagicMock()
        creds.get.return_value = "store-tok"
        fn = _tool_fn(mcp, "intercom_list_teams", credentials=creds)
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"teams": []})
            fn()
            creds.get.assert_called_once_with("intercom")

    def test_credential_store_non_string_raises(self, mcp):
        creds = MagicMock()
        creds.get.return_value = 12345
        fn = _tool_fn(mcp, "intercom_list_teams", credentials=creds)
        with pytest.raises(TypeError, match="Expected string"):
            fn()


# ---------------------------------------------------------------------------
# MCP tool function tests — Conversations
# ---------------------------------------------------------------------------


class TestIntercomSearchConversations:
    def test_no_filters_returns_recent(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"conversations": [{"id": "1"}]})
            result = fn()
            assert "conversations" in result

    def test_invalid_status(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        result = fn(status="invalid")
        assert "error" in result
        assert "status" in result["error"]

    def test_invalid_limit_too_high(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        result = fn(limit=200)
        assert "error" in result
        assert "limit" in result["error"]

    def test_invalid_limit_too_low(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        result = fn(limit=0)
        assert "error" in result

    def test_status_filter_applied(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"conversations": []})
            fn(status="open")
            body = mock_post.call_args.kwargs["json"]
            query = body["query"]
            assert query["field"] == "state"
            assert query["value"] == "open"

    def test_invalid_created_after(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        result = fn(created_after="not-a-date")
        assert "error" in result
        assert "ISO date" in result["error"]

    def test_timeout(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_conversations")
        with patch("httpx.post", side_effect=httpx.TimeoutException("t")):
            result = fn()
            assert result == {"error": "Request timed out"}


class TestIntercomGetConversation:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_get_conversation")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "conv-1", "state": "open"})
            result = fn(conversation_id="conv-1")
            assert result["id"] == "conv-1"


# ---------------------------------------------------------------------------
# MCP tool function tests — Contacts
# ---------------------------------------------------------------------------


class TestIntercomGetContact:
    def test_by_id(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_get_contact")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"id": "c1", "email": "a@b.com"})
            result = fn(contact_id="c1")
            assert result["id"] == "c1"

    def test_by_email_fallback(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_get_contact")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"data": [{"id": "c1", "email": "a@b.com"}]}
            )
            result = fn(email="a@b.com")
            assert result["id"] == "c1"

    def test_no_id_or_email(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_get_contact")
        result = fn()
        assert "error" in result
        assert "contact_id or email" in result["error"]

    def test_email_not_found(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_get_contact")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"data": []})
            result = fn(email="missing@example.com")
            assert "error" in result
            assert "No contact found" in result["error"]


class TestIntercomSearchContacts:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_contacts")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"data": [{"id": "c1"}]})
            result = fn(query="jane")
            assert "data" in result

    def test_invalid_limit(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_search_contacts")
        result = fn(query="test", limit=200)
        assert "error" in result
        assert "limit" in result["error"]


class TestIntercomCreateContact:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_create_contact")
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"id": "new-c", "role": "user"})
            result = fn(email="new@example.com")
            assert result["id"] == "new-c"

    def test_invalid_role(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_create_contact")
        result = fn(role="admin")
        assert "error" in result
        assert "role" in result["error"]


# ---------------------------------------------------------------------------
# MCP tool function tests — Notes, Tags, Assignment
# ---------------------------------------------------------------------------


class TestIntercomAddNote:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_add_note")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = _mock_response(200, {"id": "admin-1"})
            mock_post.return_value = _mock_response(200, {"type": "conversation_part"})
            result = fn(conversation_id="conv-1", body="Internal note")
            assert result["type"] == "conversation_part"


class TestIntercomAddTag:
    def test_must_provide_target(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_add_tag")
        result = fn(name="vip")
        assert "error" in result
        assert "conversation_id or contact_id" in result["error"]

    def test_cannot_provide_both_targets(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_add_tag")
        result = fn(name="vip", conversation_id="c1", contact_id="ct1")
        assert "error" in result
        assert "not both" in result["error"]

    def test_tag_conversation_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_add_tag")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = _mock_response(200, {"id": "admin-1"})
            # First post: create_or_get_tag, second: tag_conversation
            mock_post.side_effect = [
                _mock_response(200, {"id": "tag-1", "name": "vip"}),
                _mock_response(200, {"tags": {"tags": [{"id": "tag-1"}]}}),
            ]
            result = fn(name="vip", conversation_id="conv-1")
            assert "error" not in result


class TestIntercomAssignConversation:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_assign_conversation")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = _mock_response(200, {"id": "admin-1"})
            mock_post.return_value = _mock_response(
                200, {"id": "conv-1", "assignee": {"id": "admin-2"}}
            )
            result = fn(
                conversation_id="conv-1",
                assignee_id="admin-2",
            )
            assert "error" not in result

    def test_invalid_assignee_type(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_assign_conversation")
        result = fn(
            conversation_id="conv-1",
            assignee_id="1",
            assignee_type="bot",
        )
        assert "error" in result
        assert "assignee_type" in result["error"]


class TestIntercomCloseConversation:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_close_conversation")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = _mock_response(200, {"id": "admin-1"})
            mock_post.return_value = _mock_response(200, {"state": "closed"})
            result = fn(conversation_id="conv-1")
            assert "error" not in result

    def test_empty_conversation_id(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_close_conversation")
        result = fn(conversation_id="")
        assert "error" in result
        assert "required" in result["error"]


class TestIntercomListTeams:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_list_teams")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(
                200, {"teams": [{"id": "t1", "name": "Support"}]}
            )
            result = fn()
            assert "teams" in result


class TestIntercomListConversations:
    def test_success(self, mcp, monkeypatch):
        monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", "tok")
        fn = _tool_fn(mcp, "intercom_list_conversations")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"conversations": [{"id": "conv-1"}]})
            result = fn(limit=5)
            assert "conversations" in result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all Intercom tools are registered."""

    EXPECTED_TOOLS = [
        "intercom_search_conversations",
        "intercom_get_conversation",
        "intercom_get_contact",
        "intercom_search_contacts",
        "intercom_add_note",
        "intercom_add_tag",
        "intercom_assign_conversation",
        "intercom_list_teams",
        "intercom_close_conversation",
        "intercom_create_contact",
        "intercom_list_conversations",
    ]

    def test_all_tools_registered(self, mcp):
        tools = _register(mcp)
        for name in self.EXPECTED_TOOLS:
            assert name in tools, f"Tool {name} not registered"

    def test_tool_count(self, mcp):
        tools = _register(mcp)
        intercom_tools = [k for k in tools if k.startswith("intercom_")]
        assert len(intercom_tools) == len(self.EXPECTED_TOOLS)
