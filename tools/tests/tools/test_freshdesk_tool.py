"""Tests for Freshdesk tool."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.tools.freshdesk_tool import register_tools
from aden_tools.tools.freshdesk_tool.freshdesk_tool import _auth_header, _base_url

MOCK_CREDS = {
    "freshdesk": "test-api-key",
    "freshdesk_domain": "acme.freshdesk.com",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def mock_credentials():
    """Credentials adapter with API key and domain for testing."""
    return CredentialStoreAdapter.for_testing(MOCK_CREDS)


@pytest.fixture
def tool_fns(mcp: FastMCP, mock_credentials: CredentialStoreAdapter):
    """Register Freshdesk tools with mock credentials and return tool functions."""
    register_tools(mcp, credentials=mock_credentials)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def tool_fns_no_key(mcp: FastMCP):
    """Tools registered with domain only (missing API key) for error-path tests."""
    creds = CredentialStoreAdapter.for_testing({"freshdesk_domain": "acme.freshdesk.com"})
    register_tools(mcp, credentials=creds)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def tool_fns_no_domain(mcp: FastMCP):
    """Tools registered with API key only (missing domain) for error-path tests."""
    creds = CredentialStoreAdapter.for_testing({"freshdesk": "test-api-key"})
    register_tools(mcp, credentials=creds)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def tool_fns_env_only(mcp: FastMCP):
    """Tools registered with credentials=None; credentials resolved from os.environ."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


TICKET = {
    "id": 123,
    "subject": "Login issue",
    "description": "User cannot log in",
    "status": 2,
    "priority": 2,
    "type": "Incident",
    "tags": ["login"],
    "requester_id": 1,
    "responder_id": 10,
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-01T01:00:00Z",
}

CONTACT = {
    "id": 42,
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0000",
    "mobile": None,
    "company_id": None,
    "active": True,
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-01T01:00:00Z",
}

AGENT = {
    "id": 7,
    "contact_id": 99,
    "email": "agent@example.com",
    "occasional": False,
    "available": True,
    "contact": {"name": "Support Agent"},
}

GROUP = {
    "id": 3,
    "name": "Support",
    "description": "Support group",
    "unassigned_for": None,
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-01T01:00:00Z",
}


class TestHelpers:
    """Unit tests for internal helpers (_base_url, _auth_header)."""

    def test_base_url_plain_domain(self):
        assert _base_url("acme.freshdesk.com") == "https://acme.freshdesk.com/api/v2"

    def test_base_url_strips_https(self):
        assert _base_url("https://acme.freshdesk.com") == "https://acme.freshdesk.com/api/v2"

    def test_base_url_strips_http(self):
        assert _base_url("http://acme.freshdesk.com") == "https://acme.freshdesk.com/api/v2"

    def test_base_url_strips_whitespace(self):
        assert _base_url("  acme.freshdesk.com  ") == "https://acme.freshdesk.com/api/v2"

    def test_auth_header_format(self):
        import base64

        header = _auth_header("my-key")
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header[len("Basic ") :]).decode()
        assert decoded == "my-key:X"


class TestHealthCheckCredentialVerification:
    """Credential resolution and verify-credentials (health check) edge cases."""

    def test_missing_api_key_from_adapter(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]
        assert "help" in result

    def test_missing_domain_from_adapter(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]
        assert "help" in result

    def test_missing_api_key_from_env(self, tool_fns_env_only):
        with patch.dict("os.environ", {"FRESHDESK_DOMAIN": "acme.freshdesk.com"}, clear=True):
            result = tool_fns_env_only["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain_from_env(self, tool_fns_env_only):
        env = {"FRESHDESK_API_KEY": "key", "FRESHDESK_DOMAIN": ""}
        with patch.dict("os.environ", env, clear=False):
            result = tool_fns_env_only["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_both_credentials_missing_from_env(self, tool_fns_env_only):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns_env_only["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_empty_api_key_from_adapter(self, mcp: FastMCP):
        creds = CredentialStoreAdapter.for_testing(
            {"freshdesk": "", "freshdesk_domain": "acme.freshdesk.com"}
        )
        register_tools(mcp, credentials=creds)
        fn = mcp._tool_manager._tools["freshdesk_list_tickets"].fn
        result = fn()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_empty_domain_from_adapter(self, mcp: FastMCP):
        creds = CredentialStoreAdapter.for_testing({"freshdesk": "key", "freshdesk_domain": ""})
        register_tools(mcp, credentials=creds)
        fn = mcp._tool_manager._tools["freshdesk_list_tickets"].fn
        result = fn()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_domain_fallback_to_env_when_adapter_has_key_only(self, tool_fns_no_domain):
        with patch.dict("os.environ", {"FRESHDESK_DOMAIN": "acme.freshdesk.com"}, clear=False):
            with patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
                return_value=_mock_resp([TICKET]),
            ):
                result = tool_fns_no_domain["freshdesk_list_tickets"]()
        assert "error" not in result
        assert result["count"] == 1

    def test_credentials_from_env_only_success(self, tool_fns_env_only):
        with patch.dict(
            "os.environ",
            {"FRESHDESK_API_KEY": "test-key", "FRESHDESK_DOMAIN": "acme.freshdesk.com"},
            clear=False,
        ):
            with patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
                return_value=_mock_resp([TICKET]),
            ):
                result = tool_fns_env_only["freshdesk_list_tickets"]()
        assert "error" not in result
        assert result["count"] == 1

    def test_domain_whitespace_stripped_from_adapter(self, mcp: FastMCP):
        creds = CredentialStoreAdapter.for_testing(
            {"freshdesk": "key", "freshdesk_domain": "  acme.freshdesk.com  "}
        )
        register_tools(mcp, credentials=creds)
        fn = mcp._tool_manager._tools["freshdesk_list_tickets"].fn
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([TICKET]),
        ) as get_mock:
            fn()
        call_url = get_mock.call_args[0][0]
        assert "acme.freshdesk.com" in call_url
        assert "  " not in call_url

    def test_api_returns_401_unauthorized(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]
        assert "API key" in result["error"]

    def test_api_returns_403_forbidden(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 403
        resp.json.return_value = {}
        resp.text = "Forbidden"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "Forbidden" in result["error"]

    def test_api_returns_404_not_found(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 404
        resp.json.return_value = {}
        resp.text = "Not Found"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "Not found" in result["error"]

    def test_api_returns_429_rate_limited(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.json.return_value = {}
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_api_returns_500_server_error(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "500" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "timed out" in result["error"]

    def test_credentials_valid_success_200(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([TICKET]),
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" not in result
        assert result["count"] == 1
        assert result["tickets"][0]["id"] == 123


class TestFreshdeskListTickets:
    """Exhaustive tests for freshdesk_list_tickets (3.11 List tickets)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_list_tickets"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_success_empty_list(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" not in result
        assert result["tickets"] == []
        assert result["count"] == 0

    def test_success_single_ticket(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([TICKET]),
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert result["count"] == 1
        assert result["tickets"][0]["subject"] == "Login issue"
        assert result["tickets"][0]["id"] == 123

    def test_params_default_and_filter_updated_since(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([TICKET]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_tickets"](
                page=2,
                per_page=50,
                filter="new_and_my_open",
                updated_since="2026-03-01T00:00:00Z",
            )
        params = get_mock.call_args[1]["params"]
        assert params["page"] == 2
        assert params["per_page"] == 50
        assert params["filter"] == "new_and_my_open"
        assert params["updated_since"] == "2026-03-01T00:00:00Z"

    def test_request_url_is_tickets(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_tickets"]()
        assert get_mock.call_args[0][0].endswith("/tickets")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_tickets"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]


class TestFreshdeskGetTicket:
    """Exhaustive tests for freshdesk_get_ticket (3.13 Get single ticket)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_get_ticket"](ticket_id=123)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_get_ticket"](ticket_id=123)
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_missing_ticket_id(self, tool_fns):
        result = tool_fns["freshdesk_get_ticket"](ticket_id=0)
        assert "error" in result
        assert "ticket_id" in result["error"]

    def test_success_returns_ticket(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(TICKET),
        ):
            result = tool_fns["freshdesk_get_ticket"](ticket_id=123)
        assert "error" not in result
        assert result["subject"] == "Login issue"
        assert result["priority"] == 2
        assert result["id"] == 123

    def test_request_url_includes_ticket_id(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(TICKET))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_get_ticket"](ticket_id=456)
        assert get_mock.call_args[0][0].endswith("/tickets/456")

    def test_api_returns_404(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_ticket"](ticket_id=999)
        assert "error" in result
        assert "Not found" in result["error"]


class TestFreshdeskCreateTicket:
    """Exhaustive tests for freshdesk_create_ticket (3.14 Create ticket)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_create_ticket"](
            email="a@b.com", subject="S", description="D"
        )
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_required_fields(self, tool_fns):
        result = tool_fns["freshdesk_create_ticket"](
            email="",
            subject="",
            description="",
        )
        assert "error" in result
        assert "email" in result["error"] or "required" in result["error"]

    def test_success_minimal(self, tool_fns):
        created = {"id": 456, "subject": "New ticket", "status": 2}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=_mock_resp(created, 201),
        ):
            result = tool_fns["freshdesk_create_ticket"](
                email="user@example.com",
                subject="New ticket",
                description="Help needed",
            )
        assert result["result"] == "created"
        assert result["id"] == 456
        assert "url" in result

    def test_success_with_priority_status_tags(self, tool_fns):
        created = {"id": 789, "subject": "P1", "status": 2, "priority": 1}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=_mock_resp(created, 201),
        ) as post_mock:
            result = tool_fns["freshdesk_create_ticket"](
                email="u@x.com",
                subject="P1",
                description="D",
                priority=1,
                status=2,
                tags="bug,urgent",
            )
        assert result["id"] == 789
        payload = post_mock.call_args[1]["json"]
        assert payload["priority"] == 1
        assert payload["status"] == 2
        assert payload["tags"] == ["bug", "urgent"]

    def test_request_url_is_tickets_post(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=_mock_resp({"id": 1, "subject": "S", "status": 2}, 201),
        ) as post_mock:
            tool_fns["freshdesk_create_ticket"](email="a@b.com", subject="S", description="D")
        assert post_mock.call_args[0][0].endswith("/tickets")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_create_ticket"](
                email="a@b.com", subject="S", description="D"
            )
        assert "error" in result


class TestFreshdeskUpdateTicket:
    """Exhaustive tests for freshdesk_update_ticket (3.15 Update ticket)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_update_ticket"](ticket_id=123, status=3)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_ticket_id(self, tool_fns):
        result = tool_fns["freshdesk_update_ticket"](ticket_id=0)
        assert "error" in result
        assert "ticket_id" in result["error"]

    def test_missing_updates(self, tool_fns):
        result = tool_fns["freshdesk_update_ticket"](ticket_id=123)
        assert "error" in result
        assert "At least one field" in result["error"]

    def test_success_update_status_only(self, tool_fns):
        updated = dict(TICKET)
        updated["status"] = 3
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.put",
            return_value=_mock_resp(updated),
        ):
            result = tool_fns["freshdesk_update_ticket"](
                ticket_id=123,
                status=3,
            )
        assert result["status"] == 3

    def test_success_update_with_note(self, tool_fns):
        updated = dict(TICKET)
        updated["status"] = 3
        put_mock = MagicMock(return_value=_mock_resp(updated))
        post_mock = MagicMock(return_value=_mock_resp({"id": 1, "body": "Internal note"}, 201))
        with (
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.put",
                put_mock,
            ),
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
                post_mock,
            ),
        ):
            result = tool_fns["freshdesk_update_ticket"](
                ticket_id=123,
                status=3,
                note="Waiting for customer.",
                note_private=True,
            )
        assert result["status"] == 3
        assert put_mock.call_args[1]["json"] == {"status": 3}
        assert post_mock.call_args[0][0].endswith("/tickets/123/notes")
        assert post_mock.call_args[1]["json"] == {
            "body": "Waiting for customer.",
            "private": True,
        }

    def test_success_note_only_gets_ticket_then_posts_note(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(TICKET))
        post_mock = MagicMock(return_value=_mock_resp({"id": 1, "body": "Note only"}, 201))
        with (
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
                get_mock,
            ),
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
                post_mock,
            ),
        ):
            result = tool_fns["freshdesk_update_ticket"](
                ticket_id=123,
                note="Note only",
                note_private=False,
            )
        assert result["id"] == 123
        assert get_mock.called
        assert post_mock.call_args[1]["json"] == {"body": "Note only", "private": False}

    def test_note_post_failure_surfaces_error(self, tool_fns):
        updated = dict(TICKET)
        updated["status"] = 3
        put_mock = MagicMock(return_value=_mock_resp(updated))
        note_resp = MagicMock()
        note_resp.status_code = 429
        note_resp.text = "Too Many Requests"
        with (
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.put",
                put_mock,
            ),
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
                return_value=note_resp,
            ),
        ):
            result = tool_fns["freshdesk_update_ticket"](
                ticket_id=123,
                status=3,
                note="This note will fail",
            )
        assert result["status"] == 3
        assert "note_error" in result
        assert "Rate limited" in result["note_error"]

    def test_note_only_post_failure_surfaces_error(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(TICKET))
        note_resp = MagicMock()
        note_resp.status_code = 403
        note_resp.text = "Forbidden"
        with (
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
                get_mock,
            ),
            patch(
                "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
                return_value=note_resp,
            ),
        ):
            result = tool_fns["freshdesk_update_ticket"](
                ticket_id=123,
                note="This note will fail",
            )
        assert result["id"] == 123
        assert "note_error" in result
        assert "Forbidden" in result["note_error"]


class TestFreshdeskAddTicketReply:
    """Exhaustive tests for freshdesk_add_ticket_reply (3.16 public, 3.16b private note)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_add_ticket_reply"](ticket_id=123, body="Hi")
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_ticket_id(self, tool_fns):
        result = tool_fns["freshdesk_add_ticket_reply"](ticket_id=0, body="Hi")
        assert "error" in result
        assert "ticket_id" in result["error"]

    def test_missing_body(self, tool_fns):
        result = tool_fns["freshdesk_add_ticket_reply"](ticket_id=123, body="")
        assert "error" in result
        assert "body" in result["error"]

    def test_success_public_reply_default(self, tool_fns):
        reply = {
            "id": 999,
            "body": "<div>Thanks</div>",
            "body_text": "Thanks",
            "created_at": "2026-03-01T02:00:00Z",
        }
        post_mock = MagicMock(return_value=_mock_resp(reply, 201))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            post_mock,
        ):
            result = tool_fns["freshdesk_add_ticket_reply"](
                ticket_id=123,
                body="Thanks for reaching out",
            )
        assert result["id"] == 999
        assert result["public"] is True
        assert "Thanks" in result["body"]
        assert post_mock.call_args[0][0].endswith("/tickets/123/reply")
        assert post_mock.call_args[1]["json"] == {"body": "Thanks for reaching out"}

    def test_success_public_reply_with_from_email(self, tool_fns):
        post_mock = MagicMock(
            return_value=_mock_resp({"id": 1, "body": "x", "body_text": "x", "created_at": ""}, 201)
        )
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            post_mock,
        ):
            tool_fns["freshdesk_add_ticket_reply"](
                ticket_id=123,
                body="Reply",
                public=True,
                from_email="agent@example.com",
            )
        assert post_mock.call_args[1]["json"]["from_email"] == "agent@example.com"

    def test_success_private_note(self, tool_fns):
        note = {
            "id": 1000,
            "body": "<div>Internal</div>",
            "body_text": "Internal",
            "private": True,
            "created_at": "2026-03-01T03:00:00Z",
        }
        post_mock = MagicMock(return_value=_mock_resp(note, 201))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            post_mock,
        ):
            result = tool_fns["freshdesk_add_ticket_reply"](
                ticket_id=123,
                body="Internal note",
                public=False,
            )
        assert result["id"] == 1000
        assert result["public"] is False
        assert post_mock.call_args[0][0].endswith("/tickets/123/notes")
        assert post_mock.call_args[1]["json"] == {
            "body": "Internal note",
            "private": True,
        }

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_add_ticket_reply"](ticket_id=123, body="Hi")
        assert "error" in result
        assert "Unauthorized" in result["error"]


class TestFreshdeskListContacts:
    """Exhaustive tests for freshdesk_list_contacts (3.7 List contacts)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_contacts"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_success_empty_list(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_contacts"]()
        assert result["contacts"] == []
        assert result["count"] == 0

    def test_success_with_email_filter(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([CONTACT]),
        ) as get_mock:
            result = tool_fns["freshdesk_list_contacts"](email="jane@example.com")
        assert result["count"] == 1
        assert result["contacts"][0]["email"] == "jane@example.com"
        assert get_mock.call_args[1]["params"]["email"] == "jane@example.com"

    def test_params_page_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_contacts"](page=2, per_page=50)
        assert get_mock.call_args[1]["params"]["page"] == 2
        assert get_mock.call_args[1]["params"]["per_page"] == 50

    def test_request_url_is_contacts(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_contacts"]()
        assert get_mock.call_args[0][0].endswith("/contacts")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_contacts"]()
        assert "error" in result


class TestFreshdeskGetContact:
    """Exhaustive tests for freshdesk_get_contact (3.8 Get contact by ID)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_get_contact"](contact_id=42)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_contact_id_or_email_required(self, tool_fns):
        result = tool_fns["freshdesk_get_contact"](contact_id=None, email=None)
        assert "error" in result
        assert "contact_id" in result["error"] or "email" in result["error"]

    def test_success_by_id(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(CONTACT),
        ):
            result = tool_fns["freshdesk_get_contact"](contact_id=42)
        assert result["email"] == "jane@example.com"
        assert result["id"] == 42

    def test_success_by_email(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([CONTACT]),
        ):
            result = tool_fns["freshdesk_get_contact"](email="jane@example.com")
        assert result["email"] == "jane@example.com"

    def test_not_found_by_email(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_get_contact"](email="nonexistent@x.com")
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestFreshdeskCreateContact:
    """Exhaustive tests for freshdesk_create_contact (3.9 Create contact)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_create_contact"](email="a@b.com")
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_email_required(self, tool_fns):
        result = tool_fns["freshdesk_create_contact"](email="")
        assert "error" in result
        assert "email" in result["error"]

    def test_success_minimal(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=_mock_resp(CONTACT, 201),
        ):
            result = tool_fns["freshdesk_create_contact"](email="jane@example.com")
        assert result["email"] == "jane@example.com"

    def test_success_with_name_phone_company_id(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.post",
            return_value=_mock_resp(CONTACT, 201),
        ) as post_mock:
            tool_fns["freshdesk_create_contact"](
                email="j@x.com",
                name="Jane",
                phone="+1-555-0000",
                company_id=5,
            )
        payload = post_mock.call_args[1]["json"]
        assert payload["name"] == "Jane"
        assert payload["phone"] == "+1-555-0000"
        assert payload["company_id"] == 5


class TestFreshdeskUpdateContact:
    """Exhaustive tests for freshdesk_update_contact (3.10 Update contact)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_update_contact"](contact_id=42, name="New")
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_contact_id_required(self, tool_fns):
        result = tool_fns["freshdesk_update_contact"](contact_id=0)
        assert "error" in result
        assert "contact_id" in result["error"]

    def test_at_least_one_field_required(self, tool_fns):
        result = tool_fns["freshdesk_update_contact"](contact_id=42)
        assert "error" in result
        assert "At least one field" in result["error"]

    def test_success_update(self, tool_fns):
        updated = {**CONTACT, "name": "Jane Smith", "company_id": 5}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.put",
            return_value=_mock_resp(updated),
        ):
            result = tool_fns["freshdesk_update_contact"](
                contact_id=42,
                name="Jane Smith",
                company_id=5,
            )
        assert result["name"] == "Jane Smith"
        assert result["company_id"] == 5


class TestFreshdeskListAgents:
    """Exhaustive tests for freshdesk_list_agents (3.3 List agents)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_agents"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_list_agents"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_success_empty_list(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert "error" not in result
        assert result["agents"] == []
        assert result["count"] == 0

    def test_success_single_agent(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([AGENT]),
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert "error" not in result
        assert result["count"] == 1
        assert result["agents"][0]["id"] == 7
        assert result["agents"][0]["email"] == "agent@example.com"
        assert result["agents"][0]["name"] == "Support Agent"

    def test_success_multiple_agents(self, tool_fns):
        data = [
            AGENT,
            {**AGENT, "id": 8, "email": "agent2@example.com", "contact": {"name": "Agent Two"}},
        ]
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(data),
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert result["count"] == 2
        assert result["agents"][1]["email"] == "agent2@example.com"
        assert result["agents"][1]["name"] == "Agent Two"

    def test_params_default_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([AGENT]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"]()
        assert get_mock.call_args[1]["params"]["page"] == 1
        assert get_mock.call_args[1]["params"]["per_page"] == 30

    def test_params_custom_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"](page=2, per_page=50)
        assert get_mock.call_args[1]["params"]["page"] == 2
        assert get_mock.call_args[1]["params"]["per_page"] == 50

    def test_params_per_page_clamped_to_min_one(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"](per_page=0)
        assert get_mock.call_args[1]["params"]["per_page"] == 1

    def test_params_per_page_clamped_to_max_100(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"](per_page=200)
        assert get_mock.call_args[1]["params"]["per_page"] == 100

    def test_params_page_clamped_to_min_one(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"](page=0)
        assert get_mock.call_args[1]["params"]["page"] == 1

    def test_request_url_is_agents(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_agents"]()
        assert get_mock.call_args[0][0].endswith("/agents")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_api_returns_429(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert "error" in result
        assert "timed out" in result["error"]

    def test_agent_extract_optional_contact_missing(self, tool_fns):
        minimal_agent = {"id": 10, "email": "minimal@example.com"}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([minimal_agent]),
        ):
            result = tool_fns["freshdesk_list_agents"]()
        assert result["count"] == 1
        assert result["agents"][0]["id"] == 10
        assert result["agents"][0]["email"] == "minimal@example.com"
        assert result["agents"][0]["name"] is None


class TestFreshdeskGetAgent:
    """Exhaustive tests for freshdesk_get_agent (3.4 Get single agent)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_get_agent"](agent_id=7)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_get_agent"](agent_id=7)
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_missing_agent_id(self, tool_fns):
        result = tool_fns["freshdesk_get_agent"](agent_id=0)
        assert "error" in result
        assert "agent_id" in result["error"]

    def test_success_returns_agent(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(AGENT),
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=7)
        assert "error" not in result
        assert result["id"] == 7
        assert result["email"] == "agent@example.com"
        assert result["contact_id"] == 99
        assert result["name"] == "Support Agent"
        assert result["available"] is True
        assert result["occasional"] is False

    def test_request_url_includes_agent_id(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(AGENT))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_get_agent"](agent_id=42)
        assert get_mock.call_args[0][0].endswith("/agents/42")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=7)
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_api_returns_404(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=999)
        assert "error" in result
        assert "Not found" in result["error"]

    def test_api_returns_429(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=7)
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=7)
        assert "error" in result
        assert "timed out" in result["error"]

    def test_agent_extract_optional_contact_missing(self, tool_fns):
        minimal_agent = {"id": 10, "email": "minimal@example.com"}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(minimal_agent),
        ):
            result = tool_fns["freshdesk_get_agent"](agent_id=10)
        assert result["id"] == 10
        assert result["email"] == "minimal@example.com"
        assert result["name"] is None
        assert result["contact_id"] is None


class TestFreshdeskListGroups:
    """Exhaustive tests for freshdesk_list_groups (3.5 List groups)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_groups"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_list_groups"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_success_empty_list(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert "error" not in result
        assert result["groups"] == []
        assert result["count"] == 0

    def test_success_single_group(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([GROUP]),
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert "error" not in result
        assert result["count"] == 1
        assert result["groups"][0]["id"] == 3
        assert result["groups"][0]["name"] == "Support"
        assert result["groups"][0]["description"] == "Support group"

    def test_success_multiple_groups(self, tool_fns):
        data = [
            GROUP,
            {**GROUP, "id": 4, "name": "Sales", "description": "Sales team"},
        ]
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(data),
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert result["count"] == 2
        assert result["groups"][1]["name"] == "Sales"
        assert result["groups"][1]["description"] == "Sales team"

    def test_params_default_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_groups"]()
        assert get_mock.call_args[1]["params"]["page"] == 1
        assert get_mock.call_args[1]["params"]["per_page"] == 30

    def test_params_custom_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_groups"](page=3, per_page=50)
        assert get_mock.call_args[1]["params"]["page"] == 3
        assert get_mock.call_args[1]["params"]["per_page"] == 50

    def test_params_per_page_clamped_to_max_100(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_groups"](per_page=200)
        assert get_mock.call_args[1]["params"]["per_page"] == 100

    def test_params_per_page_clamped_to_min_one(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_groups"](per_page=0)
        assert get_mock.call_args[1]["params"]["per_page"] == 1

    def test_request_url_is_groups(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_groups"]()
        assert get_mock.call_args[0][0].endswith("/groups")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_api_returns_429(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert "error" in result
        assert "timed out" in result["error"]

    def test_group_extract_optional_fields_missing(self, tool_fns):
        minimal_group = {"id": 10, "name": "Minimal Group"}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([minimal_group]),
        ):
            result = tool_fns["freshdesk_list_groups"]()
        assert result["count"] == 1
        assert result["groups"][0]["id"] == 10
        assert result["groups"][0]["name"] == "Minimal Group"
        assert result["groups"][0]["description"] is None
        assert result["groups"][0]["unassigned_for"] is None


class TestFreshdeskGetGroup:
    """Exhaustive tests for freshdesk_get_group (3.6 Get single group)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_get_group"](group_id=3)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_get_group"](group_id=3)
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_missing_group_id(self, tool_fns):
        result = tool_fns["freshdesk_get_group"](group_id=0)
        assert "error" in result
        assert "group_id" in result["error"]

    def test_success_returns_group(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(GROUP),
        ):
            result = tool_fns["freshdesk_get_group"](group_id=3)
        assert "error" not in result
        assert result["id"] == 3
        assert result["name"] == "Support"
        assert result["description"] == "Support group"
        assert result["unassigned_for"] is None
        assert "created_at" in result
        assert "updated_at" in result

    def test_request_url_includes_group_id(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(GROUP))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_get_group"](group_id=42)
        assert get_mock.call_args[0][0].endswith("/groups/42")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_group"](group_id=3)
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_api_returns_404(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_group"](group_id=999)
        assert "error" in result
        assert "Not found" in result["error"]

    def test_api_returns_429(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_group"](group_id=3)
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_get_group"](group_id=3)
        assert "error" in result
        assert "timed out" in result["error"]

    def test_group_extract_optional_fields_missing(self, tool_fns):
        minimal_group = {"id": 10, "name": "Minimal"}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(minimal_group),
        ):
            result = tool_fns["freshdesk_get_group"](group_id=10)
        assert result["id"] == 10
        assert result["name"] == "Minimal"
        assert result["description"] is None
        assert result["unassigned_for"] is None


COMPANY = {
    "id": 5,
    "name": "Acme Corp",
    "description": "Acme Corporation",
    "domains": ["acme.com"],
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-01T01:00:00Z",
}


class TestFreshdeskFilterTickets:
    """Exhaustive tests for freshdesk_filter_tickets (3.12 Search/filter tickets)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_filter_tickets"](query="priority:3")
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_query_required(self, tool_fns):
        result = tool_fns["freshdesk_filter_tickets"](query="")
        assert "error" in result
        assert "query" in result["error"]

    def test_success_query_wrapped_in_quotes(self, tool_fns):
        data = {"total": 2, "results": [TICKET, {**TICKET, "id": 124}]}
        get_mock = MagicMock(return_value=_mock_resp(data))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            result = tool_fns["freshdesk_filter_tickets"](query="priority:3")
        assert result["total"] == 2
        assert len(result["tickets"]) == 2
        assert get_mock.call_args[1]["params"]["query"] == '"priority:3"'

    def test_query_already_quoted_not_double_quoted(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp({"total": 0, "results": []}))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_filter_tickets"](query='"status:2"')
        assert get_mock.call_args[1]["params"]["query"] == '"status:2"'

    def test_page_param_clamped(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp({"total": 0, "results": []}))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_filter_tickets"](query="x", page=1)
        assert get_mock.call_args[1]["params"]["page"] == 1

    def test_page_param_clamped_to_max_10(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp({"total": 0, "results": []}))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_filter_tickets"](query="x", page=15)
        assert get_mock.call_args[1]["params"]["page"] == 10

    def test_page_param_clamped_to_min_1(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp({"total": 0, "results": []}))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_filter_tickets"](query="x", page=0)
        assert get_mock.call_args[1]["params"]["page"] == 1

    def test_request_url_is_search_tickets(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp({"total": 0, "results": []}))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_filter_tickets"](query="x")
        assert "/search/tickets" in get_mock.call_args[0][0]

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_filter_tickets"](query="priority:3")
        assert "error" in result


class TestFreshdeskListTicketConversations:
    """Exhaustive tests for freshdesk_list_ticket_conversations (3.17)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_ticket_conversations"](ticket_id=123)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_ticket_id_required(self, tool_fns):
        result = tool_fns["freshdesk_list_ticket_conversations"](ticket_id=0)
        assert "error" in result
        assert "ticket_id" in result["error"]

    def test_success_empty(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_ticket_conversations"](ticket_id=123)
        assert result["conversations"] == []
        assert result["count"] == 0

    def test_success_with_conversations(self, tool_fns):
        convos = [
            {
                "id": 1,
                "body_text": "First reply",
                "private": False,
                "user_id": 10,
                "created_at": "2026-03-01T02:00:00Z",
            },
        ]
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(convos),
        ):
            result = tool_fns["freshdesk_list_ticket_conversations"](ticket_id=123)
        assert result["count"] == 1
        assert result["conversations"][0]["body_text"] == "First reply"
        assert result["conversations"][0]["private"] is False

    def test_params_page_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_ticket_conversations"](ticket_id=123, page=2, per_page=10)
        assert get_mock.call_args[1]["params"]["page"] == 2
        assert get_mock.call_args[1]["params"]["per_page"] == 10

    def test_request_url_includes_ticket_id(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_ticket_conversations"](ticket_id=456)
        assert get_mock.call_args[0][0].endswith("/tickets/456/conversations")


class TestFreshdeskListCompanies:
    """Exhaustive tests for freshdesk_list_companies (3.2 List companies)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_list_companies"]()
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_list_companies"]()
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_success_empty_list(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([]),
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" not in result
        assert result["companies"] == []
        assert result["count"] == 0

    def test_success_single_company(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([COMPANY]),
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" not in result
        assert result["count"] == 1
        assert result["companies"][0]["id"] == 5
        assert result["companies"][0]["name"] == "Acme Corp"
        assert result["companies"][0]["domains"] == ["acme.com"]

    def test_success_multiple_companies(self, tool_fns):
        data = [
            COMPANY,
            {**COMPANY, "id": 6, "name": "Beta Inc"},
            {**COMPANY, "id": 7, "name": "Gamma LLC"},
        ]
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(data),
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert result["count"] == 3
        assert result["companies"][1]["name"] == "Beta Inc"
        assert result["companies"][2]["name"] == "Gamma LLC"

    def test_params_default_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([COMPANY]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"]()
        assert get_mock.call_args[1]["params"]["page"] == 1
        assert get_mock.call_args[1]["params"]["per_page"] == 30

    def test_params_custom_page_and_per_page(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([COMPANY]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"](page=2, per_page=50)
        assert get_mock.call_args[1]["params"]["page"] == 2
        assert get_mock.call_args[1]["params"]["per_page"] == 50

    def test_params_per_page_clamped_to_min_one(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"](per_page=0)
        assert get_mock.call_args[1]["params"]["per_page"] == 1

    def test_params_per_page_clamped_to_max_100(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"](per_page=200)
        assert get_mock.call_args[1]["params"]["per_page"] == 100

    def test_params_page_clamped_to_min_one(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"](page=0)
        assert get_mock.call_args[1]["params"]["page"] == 1

    def test_params_updated_since_passed(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"](updated_since="2026-03-01T00:00:00Z")
        assert get_mock.call_args[1]["params"]["updated_since"] == "2026-03-01T00:00:00Z"

    def test_request_url_is_companies(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp([]))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_list_companies"]()
        assert get_mock.call_args[0][0].endswith("/companies")

    def test_api_returns_401(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {}
        resp.text = "Unauthorized"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_api_returns_403(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" in result
        assert "Forbidden" in result["error"]

    def test_api_returns_429(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" in result
        assert "Rate limited" in result["error"]

    def test_request_timeout(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert "error" in result
        assert "timed out" in result["error"]

    def test_company_extract_optional_fields_missing(self, tool_fns):
        minimal_company = {"id": 10, "name": "Minimal Co"}
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp([minimal_company]),
        ):
            result = tool_fns["freshdesk_list_companies"]()
        assert result["count"] == 1
        assert result["companies"][0]["id"] == 10
        assert result["companies"][0]["name"] == "Minimal Co"
        assert result["companies"][0]["description"] is None
        assert result["companies"][0]["domains"] == []
        assert result["companies"][0]["note"] is None


class TestFreshdeskGetCompany:
    """Exhaustive tests for freshdesk_get_company (Get single company)."""

    def test_missing_api_key(self, tool_fns_no_key):
        result = tool_fns_no_key["freshdesk_get_company"](company_id=5)
        assert "error" in result
        assert "FRESHDESK_API_KEY" in result["error"]

    def test_missing_domain(self, tool_fns_no_domain):
        result = tool_fns_no_domain["freshdesk_get_company"](company_id=5)
        assert "error" in result
        assert "FRESHDESK_DOMAIN" in result["error"]

    def test_company_id_required(self, tool_fns):
        result = tool_fns["freshdesk_get_company"](company_id=0)
        assert "error" in result
        assert "company_id" in result["error"]

    def test_success_returns_company(self, tool_fns):
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=_mock_resp(COMPANY),
        ):
            result = tool_fns["freshdesk_get_company"](company_id=5)
        assert "error" not in result
        assert result["id"] == 5
        assert result["name"] == "Acme Corp"
        assert result["domains"] == ["acme.com"]

    def test_request_url_includes_company_id(self, tool_fns):
        get_mock = MagicMock(return_value=_mock_resp(COMPANY))
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            get_mock,
        ):
            tool_fns["freshdesk_get_company"](company_id=42)
        assert get_mock.call_args[0][0].endswith("/companies/42")

    def test_api_returns_404(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        with patch(
            "aden_tools.tools.freshdesk_tool.freshdesk_tool.httpx.get",
            return_value=resp,
        ):
            result = tool_fns["freshdesk_get_company"](company_id=999)
        assert "error" in result
        assert "Not found" in result["error"]
