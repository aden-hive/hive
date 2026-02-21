"""
Tests for Intercom tool and credential spec.

Covers:
- _IntercomClient methods (search, get, reply, assign, tag)
- Error handling (401, 403, 404, 429, 500, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 8 MCP tool functions
- Input validation (missing params, invalid values)
- Credential spec registration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.intercom_tool.intercom_tool import (
    INTERCOM_API_BASE,
    _IntercomClient,
    register_tools,
)

# --- _IntercomClient tests ---


class TestIntercomClientHeaders:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    def test_authorization_header(self):
        assert self.client._headers["Authorization"] == "Bearer test-token"

    def test_intercom_version_header(self):
        assert self.client._headers["Intercom-Version"] == "2.11"

    def test_content_type_header(self):
        assert self.client._headers["Content-Type"] == "application/json"


class TestHandleResponse:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    def test_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"type": "team.list", "teams": []}
        assert self.client._handle_response(response) == {"type": "team.list", "teams": []}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_error_codes(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_generic_error_with_intercom_error_format(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {
            "type": "error.list",
            "errors": [{"code": "server_error", "message": "Something went wrong"}],
        }
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]
        assert "Something went wrong" in result["error"]

    def test_generic_error_fallback_to_text(self):
        response = MagicMock()
        response.status_code = 500
        response.json.side_effect = Exception("not json")
        response.text = "Internal Server Error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Internal Server Error" in result["error"]


class TestGetAdminId:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_fetches_admin_id(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "admin", "id": "12345"}
        mock_get.return_value = mock_response

        result = self.client._get_admin_id()

        assert result == "12345"
        mock_get.assert_called_once_with(
            f"{INTERCOM_API_BASE}/me",
            headers=self.client._headers,
            timeout=30.0,
        )

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_caches_admin_id(self, mock_get):
        """Second call should use cached value, not hit API again."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "admin", "id": "12345"}
        mock_get.return_value = mock_response

        self.client._get_admin_id()
        self.client._get_admin_id()

        # Should only call the API once
        mock_get.assert_called_once()

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_returns_error_on_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = self.client._get_admin_id()

        assert isinstance(result, dict)
        assert "error" in result


class TestListTeams:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_list_teams_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "team.list",
            "teams": [{"type": "team", "id": "1", "name": "Support"}],
        }
        mock_get.return_value = mock_response

        result = self.client.list_teams()

        mock_get.assert_called_once_with(
            f"{INTERCOM_API_BASE}/teams",
            headers=self.client._headers,
            timeout=30.0,
        )
        assert result["type"] == "team.list"
        assert len(result["teams"]) == 1


class TestListTags:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_list_tags_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "list",
            "data": [{"type": "tag", "id": "1", "name": "VIP"}],
        }
        mock_get.return_value = mock_response

        result = self.client.list_tags()

        mock_get.assert_called_once_with(
            f"{INTERCOM_API_BASE}/tags",
            headers=self.client._headers,
            timeout=30.0,
        )
        assert result["type"] == "list"
        assert len(result["data"]) == 1


class TestSearchContacts:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_search_contacts(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "list",
            "data": [{"type": "contact", "id": "123", "email": "test@example.com"}],
        }
        mock_post.return_value = mock_response

        query = {"field": "email", "operator": "=", "value": "test@example.com"}
        result = self.client.search_contacts(query, limit=5)

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/contacts/search",
            headers=self.client._headers,
            json={"query": query, "pagination": {"per_page": 5}},
            timeout=30.0,
        )
        assert result["type"] == "list"
        assert len(result["data"]) == 1


class TestGetContact:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_get_contact_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "contact",
            "id": "123",
            "email": "test@example.com",
        }
        mock_get.return_value = mock_response

        result = self.client.get_contact("123")

        mock_get.assert_called_once_with(
            f"{INTERCOM_API_BASE}/contacts/123",
            headers=self.client._headers,
            timeout=30.0,
        )
        assert result["type"] == "contact"
        assert result["id"] == "123"


class TestGetConversation:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_get_conversation_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "conversation",
            "id": "456",
            "title": "Help needed",
        }
        mock_get.return_value = mock_response

        result = self.client.get_conversation("456")

        mock_get.assert_called_once_with(
            f"{INTERCOM_API_BASE}/conversations/456",
            headers=self.client._headers,
            params={"display_as": "plaintext"},
            timeout=30.0,
        )
        assert result["type"] == "conversation"
        assert result["id"] == "456"


class TestSearchConversations:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_search_conversations_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "type": "conversation.list",
            "conversations": [{"type": "conversation", "id": "456"}],
        }
        mock_post.return_value = mock_response

        query = {"field": "updated_at", "operator": ">", "value": "1609459200"}
        result = self.client.search_conversations(query, limit=10)

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/conversations/search",
            headers=self.client._headers,
            json={"query": query, "pagination": {"per_page": 10}},
            timeout=30.0,
        )
        assert result["type"] == "conversation.list"
        assert len(result["conversations"]) == 1


class TestReplyToConversation:
    def setup_method(self):
        self.client = _IntercomClient("test-token")
        self.client._admin_id = "admin-1"  # pre-cache to avoid mocking /me

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_reply_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "conversation", "id": "456"}
        mock_post.return_value = mock_response

        result = self.client.reply_to_conversation(
            "456",
            body="Hello!",
            message_type="comment",
        )

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/conversations/456/reply",
            headers=self.client._headers,
            json={
                "type": "admin",
                "admin_id": "admin-1",
                "message_type": "comment",
                "body": "Hello!",
            },
            timeout=30.0,
        )
        assert result["type"] == "conversation"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_reply_returns_error_when_admin_id_fails(self, mock_get):
        client = _IntercomClient("bad-token")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = client.reply_to_conversation("456", body="Hello!")

        assert "error" in result


class TestAssignConversation:
    def setup_method(self):
        self.client = _IntercomClient("test-token")
        self.client._admin_id = "admin-1"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_assign_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "conversation", "id": "456"}
        mock_post.return_value = mock_response

        result = self.client.assign_conversation("456", assignee_id="admin-2", body="Reassigning")

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/conversations/456/parts",
            headers=self.client._headers,
            json={
                "type": "admin",
                "admin_id": "admin-1",
                "assignee_id": "admin-2",
                "message_type": "assignment",
                "body": "Reassigning",
            },
            timeout=30.0,
        )
        assert result["type"] == "conversation"


class TestCreateOrGetTag:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_create_tag_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "tag", "id": "99", "name": "VIP"}
        mock_post.return_value = mock_response

        result = self.client.create_or_get_tag("VIP")

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/tags",
            headers=self.client._headers,
            json={"name": "VIP"},
            timeout=30.0,
        )
        assert result["type"] == "tag"
        assert result["name"] == "VIP"


class TestTagConversation:
    def setup_method(self):
        self.client = _IntercomClient("test-token")
        self.client._admin_id = "admin-1"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_tag_conversation_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "tag", "id": "99"}
        mock_post.return_value = mock_response

        result = self.client.tag_conversation("456", "99")

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/conversations/456/tags",
            headers=self.client._headers,
            json={"id": "99", "admin_id": "admin-1"},
            timeout=30.0,
        )
        assert result["type"] == "tag"


class TestTagContact:
    def setup_method(self):
        self.client = _IntercomClient("test-token")

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_tag_contact_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "tag", "id": "99"}
        mock_post.return_value = mock_response

        result = self.client.tag_contact("123", "99")

        mock_post.assert_called_once_with(
            f"{INTERCOM_API_BASE}/contacts/123/tags",
            headers=self.client._headers,
            json={"id": "99"},
            timeout=30.0,
        )
        assert result["type"] == "tag"


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 8

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        search_fn = next(fn for fn in registered_fns if fn.__name__ == "intercom_list_teams")
        result = search_fn()
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "test-token"

        register_tools(mcp, credentials=cred_manager)

        list_fn = next(fn for fn in registered_fns if fn.__name__ == "intercom_list_teams")

        with patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"type": "team.list", "teams": []}
            mock_get.return_value = mock_response

            result = list_fn()

        cred_manager.get.assert_called_with("intercom")
        assert result["type"] == "team.list"

    def test_credentials_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        list_fn = next(fn for fn in registered_fns if fn.__name__ == "intercom_list_teams")

        with (
            patch.dict("os.environ", {"INTERCOM_ACCESS_TOKEN": "env-token"}),
            patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get") as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"type": "team.list", "teams": []}
            mock_get.return_value = mock_response

            result = list_fn()

        assert result["type"] == "team.list"
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer env-token"


# --- Individual tool function tests ---


class TestConversationTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_search_conversations(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"type": "conversation.list", "conversations": [{"id": "1"}]}
            ),
        )
        result = self._fn("intercom_search_conversations")(status="open")
        assert result["type"] == "conversation.list"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_get_conversation(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"type": "conversation", "id": "1"})
        )
        result = self._fn("intercom_get_conversation")(conversation_id="1")
        assert result["id"] == "1"

    def test_search_conversations_invalid_status(self):
        result = self._fn("intercom_search_conversations")(status="invalid")
        assert "error" in result

    def test_search_conversations_invalid_limit(self):
        result = self._fn("intercom_search_conversations")(limit=0)
        assert "error" in result

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_search_conversations_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("intercom_search_conversations")()
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_get_conversation_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn("intercom_get_conversation")(conversation_id="1")
        assert "error" in result
        assert "Network error" in result["error"]


class TestContactTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_get_contact_by_id(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"type": "contact", "id": "1"})
        )
        result = self._fn("intercom_get_contact")(contact_id="1")
        assert result["id"] == "1"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_get_contact_by_email(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "type": "list",
                    "data": [{"type": "contact", "id": "2", "email": "a@b.com"}],
                }
            ),
        )
        result = self._fn("intercom_get_contact")(email="a@b.com")
        assert result["id"] == "2"

    def test_get_contact_missing_params(self):
        result = self._fn("intercom_get_contact")()
        assert "error" in result

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_search_contacts(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"type": "list", "data": [{"id": "1"}]}),
        )
        result = self._fn("intercom_search_contacts")(query="john")
        assert result["type"] == "list"

    def test_search_contacts_invalid_limit(self):
        result = self._fn("intercom_search_contacts")(query="john", limit=200)
        assert "error" in result


class TestNoteTagAssignTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_add_note(self, mock_post, mock_get):
        # Mock /me for admin_id
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "admin-1"})
        )
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"type": "conversation", "id": "1"})
        )
        result = self._fn("intercom_add_note")(conversation_id="1", body="Triage note")
        assert result["type"] == "conversation"

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_add_tag_to_conversation(self, mock_post, mock_get):
        # Mock /me for admin_id
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "admin-1"})
        )
        # First post: create_or_get_tag, second: tag_conversation
        mock_post.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"type": "tag", "id": "99", "name": "VIP"}),
            ),
            MagicMock(status_code=200, json=MagicMock(return_value={"type": "tag", "id": "99"})),
        ]
        result = self._fn("intercom_add_tag")(name="VIP", conversation_id="1")
        assert result["type"] == "tag"

    def test_add_tag_missing_target(self):
        result = self._fn("intercom_add_tag")(name="VIP")
        assert "error" in result

    def test_add_tag_both_targets(self):
        result = self._fn("intercom_add_tag")(name="VIP", conversation_id="1", contact_id="2")
        assert "error" in result
        assert "not both" in result["error"]

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.post")
    def test_assign_conversation(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"id": "admin-1"})
        )
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"type": "conversation", "id": "1"})
        )
        result = self._fn("intercom_assign_conversation")(
            conversation_id="1", assignee_id="admin-2"
        )
        assert result["type"] == "conversation"

    def test_assign_conversation_invalid_type(self):
        result = self._fn("intercom_assign_conversation")(
            conversation_id="1", assignee_id="2", assignee_type="invalid"
        )
        assert "error" in result

    @patch("aden_tools.tools.intercom_tool.intercom_tool.httpx.get")
    def test_list_teams(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"type": "team.list", "teams": []}),
        )
        result = self._fn("intercom_list_teams")()
        assert result["type"] == "team.list"


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_intercom_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "intercom" in CREDENTIAL_SPECS

    def test_intercom_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["intercom"]
        assert spec.env_var == "INTERCOM_ACCESS_TOKEN"

    def test_intercom_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["intercom"]
        assert "intercom_search_conversations" in spec.tools
        assert "intercom_list_teams" in spec.tools
        assert len(spec.tools) == 8
