"""Tests for the Atomic Mail tool (auth flow, JMAP client, MCP tools)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.credentials.health_check import AtomicMailHealthChecker
from aden_tools.tools.atomicmail_tool import auth as auth_mod, register_tools
from aden_tools.tools.atomicmail_tool.auth import (
    AtomicMailAuthError,
    AtomicMailSession,
    decode_jwt_payload,
    has_leading_zero_bits,
    jwt_expired,
    solve_pow,
)

AUTH = "https://auth.atomicmail.ai"
API = "https://api.atomicmail.ai"
JMAP_URL = "https://api.atomicmail.ai/jmap/"
ACCOUNT = "acc-1"
MAILBOXES = {"inbox": "mb-inbox", "sent": "mb-sent"}


def make_jwt(payload: dict[str, Any]) -> str:
    def enc(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


def _response(status: int, url: str, *, json_body: Any = None, bearer: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    return httpx.Response(status, json=json_body, headers=headers, request=httpx.Request("POST", url))


class FakeAtomicMail:
    """In-memory stand-in for the auth service and the JMAP endpoint.

    ``jmap_handler`` receives each JMAP method call ``(name, args, call_id)``
    and returns the response args; override it per test.
    """

    def __init__(self, valid_key: str = "test-key", inbox_id: str = "my-agent") -> None:
        self.valid_key = valid_key
        self.inbox_id = inbox_id
        self.calls: dict[str, int] = {"challenge": 0, "session": 0, "capability": 0, "well_known": 0, "jmap": 0}
        self.jmap_envelopes: list[dict[str, Any]] = []
        self.capability_ttl = 120
        self.capability_status: list[int] = []  # statuses to return before succeeding
        self.jmap_status: list[int] = []
        self.jmap_handler = self.default_jmap_handler

    def default_jmap_handler(self, name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
        if name == "Mailbox/query":
            mailbox = MAILBOXES.get(args["filter"]["role"])
            return {"ids": [mailbox] if mailbox else []}
        if name == "Email/query":
            return {"ids": ["e1"]}
        if name == "Email/get":
            return {"list": [{"id": "e1", "subject": "Hello", "keywords": {}}], "notFound": []}
        if name == "Email/set":
            if "create" in args:
                return {"created": {"d1": {"id": "e-new"}}}
            return {"updated": dict.fromkeys(args["update"])}
        if name == "EmailSubmission/set":
            return {"created": {"s1": {"id": "sub-1"}}}
        raise AssertionError(f"unexpected JMAP method {name}")

    def post(self, url: str, headers: dict[str, str] | None = None, json: Any = None, **_: Any) -> httpx.Response:
        if url == f"{AUTH}/api/v1/challenge":
            self.calls["challenge"] += 1
            return _response(200, url, bearer=make_jwt({"jti": "chal-123", "difficulty": 1}))
        if url == f"{AUTH}/api/v1/session":
            self.calls["session"] += 1
            if json["apiKey"] != self.valid_key:
                return _response(401, url, json_body={"error": {"message": "unknown api key", "hint": "check the key"}})
            return _response(200, url, bearer=make_jwt({"exp": time.time() + 3600}))
        if url == f"{AUTH}/api/v1/capability":
            self.calls["capability"] += 1
            if self.capability_status:
                return _response(self.capability_status.pop(0), url, json_body={"error": {"message": "expired"}})
            token = make_jwt({"exp": time.time() + self.capability_ttl, "inboxId": self.inbox_id})
            return _response(200, url, bearer=token)
        if url == JMAP_URL:
            self.calls["jmap"] += 1
            if self.jmap_status:
                return _response(self.jmap_status.pop(0), url, json_body={})
            self.jmap_envelopes.append(json)
            responses = [[name, self.jmap_handler(name, args, cid), cid] for name, args, cid in json["methodCalls"]]
            return _response(200, url, json_body={"methodResponses": responses})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, **_: Any) -> httpx.Response:
        assert url == f"{API}/.well-known/jmap"
        self.calls["well_known"] += 1
        return _response(
            200,
            url,
            json_body={"apiUrl": JMAP_URL, "primaryAccounts": {"urn:ietf:params:jmap:mail": ACCOUNT}},
        )

    def method_calls(self) -> list[list[Any]]:
        return [call for env in self.jmap_envelopes for call in env["methodCalls"]]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "ATOMIC_MAIL_API_KEY",
        "ATOMIC_MAIL_AUTH_URL",
        "ATOMIC_MAIL_API_URL",
        "ATOMIC_MAIL_INBOX_DOMAIN",
        "ATOMIC_MAIL_SCRYPT_SALT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake():
    """Patch httpx and the PoW solver so the full flow runs offline and fast."""
    server = FakeAtomicMail()
    with (
        patch("httpx.post", side_effect=server.post),
        patch("httpx.get", side_effect=server.get),
        patch.object(auth_mod, "solve_pow", return_value=("00ab", "7")),
    ):
        yield server


@pytest.fixture
def get_tool_fn():
    mcp = FastMCP("test-server")
    register_tools(mcp)

    def _get(name: str):
        return mcp._tool_manager._tools[name].fn

    return _get


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ATOMIC_MAIL_API_KEY", "test-key")


# ============================================================================
# Proof-of-work and JWT helpers
# ============================================================================


class TestPowAndJwt:
    def test_leading_zero_bits(self):
        assert has_leading_zero_bits(b"\x00\x0f", 12)
        assert not has_leading_zero_bits(b"\x00\x1f", 12)
        assert has_leading_zero_bits(b"\x00\x00", 16)
        assert has_leading_zero_bits(b"\xff", 0)
        assert not has_leading_zero_bits(b"\x00", 9)

    def test_solve_pow_meets_difficulty(self):
        pow_hex, nonce = solve_pow("challenge", 3, "salt-hex")
        digest = hashlib.scrypt(
            f"challenge:{nonce}".encode(),
            salt=b"salt-hex",  # salt is the UTF-8 text, not decoded hex
            n=16_384,
            r=8,
            p=1,
            dklen=64,
        )
        assert digest.hex() == pow_hex
        assert has_leading_zero_bits(digest, 3)

    def test_solve_pow_time_limit(self):
        with pytest.raises(AtomicMailAuthError, match="not solved"):
            solve_pow("challenge", 512, "salt", time_limit_s=0)

    def test_decode_and_expiry(self):
        token = make_jwt({"exp": time.time() + 100, "inboxId": "x"})
        assert decode_jwt_payload(token)["inboxId"] == "x"
        assert not jwt_expired(token, margin_s=20)
        assert jwt_expired(token, margin_s=200)
        assert jwt_expired(None, 0)
        assert jwt_expired("not-a-jwt", 0)
        assert jwt_expired(make_jwt({"no": "exp"}), 0)


# ============================================================================
# Session / token lifecycle
# ============================================================================


class TestAtomicMailSession:
    def test_login_once_then_reuse_tokens(self, fake):
        session = AtomicMailSession("test-key")
        first = session.capability_token()
        assert session.capability_token() == first
        assert fake.calls["challenge"] == 1
        assert fake.calls["session"] == 1
        assert fake.calls["capability"] == 1

    def test_session_sends_pow_and_key(self, fake):
        AtomicMailSession("test-key").capability_token()
        with patch("httpx.post", side_effect=fake.post) as post:
            fake.calls["challenge"] = 0
            AtomicMailSession("test-key").capability_token()
        session_call = next(c for c in post.call_args_list if c.args[0].endswith("/session"))
        assert session_call.kwargs["json"] == {"powHex": "00ab", "nonce": "7", "apiKey": "test-key"}
        assert session_call.kwargs["headers"]["Authorization"].startswith("Bearer ")

    def test_expiring_capability_is_reminted_without_new_pow(self, fake):
        fake.capability_ttl = 10  # inside the 20s safety margin: always "expired"
        session = AtomicMailSession("test-key")
        session.capability_token()
        session.capability_token()
        assert fake.calls["capability"] == 2
        assert fake.calls["challenge"] == 1

    def test_revoked_session_triggers_relogin(self, fake):
        fake.capability_status = [401]
        AtomicMailSession("test-key").capability_token()
        assert fake.calls["challenge"] == 2
        assert fake.calls["capability"] == 2

    def test_invalid_key_raises(self, fake):
        with pytest.raises(AtomicMailAuthError) as exc:
            AtomicMailSession("wrong-key").capability_token()
        assert exc.value.status_code == 401
        assert "Invalid Atomic Mail API key" in str(exc.value)
        assert exc.value.hint == "check the key"

    def test_inbox_address(self, fake, monkeypatch):
        session = AtomicMailSession("test-key")
        assert session.inbox_address is None
        session.capability_token()
        assert session.inbox_address == "my-agent@atomicmail.ai"

        monkeypatch.setenv("ATOMIC_MAIL_INBOX_DOMAIN", "@corp.example")
        custom = AtomicMailSession("test-key")
        custom.capability_token()
        assert custom.inbox_address == "my-agent@corp.example"

        fake.inbox_id = "bot@other.example"
        full = AtomicMailSession("test-key")
        full.capability_token()
        assert full.inbox_address == "bot@other.example"

    def test_jmap_session_discovered_once(self, fake):
        session = AtomicMailSession("test-key")
        assert session.jmap_api_url == JMAP_URL
        assert session.account_id == ACCOUNT
        assert fake.calls["well_known"] == 1


# ============================================================================
# Credentials
# ============================================================================


class TestCredentials:
    @pytest.mark.parametrize(
        "tool,kwargs",
        [
            ("atomicmail_get_address", {}),
            ("atomicmail_send", {"to": "a@b.com", "subject": "s", "body": "b"}),
            ("atomicmail_list_emails", {}),
            ("atomicmail_read_email", {"email_id": "e1"}),
            ("atomicmail_search", {"query": "code"}),
            ("atomicmail_reply", {"email_id": "e1", "body": "b"}),
            ("atomicmail_mark_read", {"email_ids": "e1"}),
        ],
    )
    def test_missing_credentials(self, get_tool_fn, tool, kwargs):
        result = get_tool_fn(tool)(**kwargs)
        assert result["error"] == "Atomic Mail credentials not configured"
        assert "ATOMIC_MAIL_API_KEY" in result["help"]

    def test_uses_credential_store(self, fake):
        store = MagicMock()
        store.get.return_value = "test-key"
        mcp = FastMCP("test-server")
        register_tools(mcp, credentials=store)
        result = mcp._tool_manager._tools["atomicmail_get_address"].fn()
        store.get.assert_called_with("atomicmail")
        assert result == {"success": True, "address": "my-agent@atomicmail.ai"}

    def test_invalid_key_returns_error_with_hint(self, fake, get_tool_fn, monkeypatch):
        monkeypatch.setenv("ATOMIC_MAIL_API_KEY", "wrong-key")
        result = get_tool_fn("atomicmail_list_emails")()
        assert "Invalid Atomic Mail API key" in result["error"]
        assert result["help"] == "check the key"

    def test_session_shared_across_tool_calls(self, fake, get_tool_fn, with_key):
        get_tool_fn("atomicmail_get_address")()
        get_tool_fn("atomicmail_list_emails")()
        get_tool_fn("atomicmail_search")(query="x")
        assert fake.calls["challenge"] == 1


# ============================================================================
# Send / reply
# ============================================================================


class TestSend:
    def test_send_builds_jmap_request(self, fake, get_tool_fn, with_key):
        result = get_tool_fn("atomicmail_send")(
            to="a@example.com, b@example.com",
            subject="Hi",
            body="Hello there",
            cc="c@example.com",
        )
        assert result == {"success": True, "email_id": "e-new", "submission_id": "sub-1", "from": "my-agent@atomicmail.ai"}

        envelope = fake.jmap_envelopes[-1]
        assert "urn:ietf:params:jmap:submission" in envelope["using"]
        (_, email_set, _), (_, submission, _) = envelope["methodCalls"]
        draft = email_set["create"]["d1"]
        assert email_set["accountId"] == ACCOUNT
        assert draft["mailboxIds"] == {"mb-sent": True}
        assert draft["from"] == [{"email": "my-agent@atomicmail.ai"}]
        assert draft["to"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]
        assert draft["cc"] == [{"email": "c@example.com"}]
        assert draft["bodyValues"] == {"text": {"value": "Hello there"}}
        assert "htmlBody" not in draft
        assert submission["create"]["s1"]["emailId"] == "#d1"
        rcpt = [r["email"] for r in submission["create"]["s1"]["envelope"]["rcptTo"]]
        assert rcpt == ["a@example.com", "b@example.com", "c@example.com"]
        assert submission["onSuccessUpdateEmail"] == {"#s1": {"keywords/$draft": None, "keywords/$sent": True}}

    def test_send_with_html(self, fake, get_tool_fn, with_key):
        get_tool_fn("atomicmail_send")(to="a@example.com", subject="Hi", body="text", html_body="<p>hi</p>")
        draft = fake.jmap_envelopes[-1]["methodCalls"][0][1]["create"]["d1"]
        assert draft["htmlBody"] == [{"partId": "html", "type": "text/html"}]
        assert draft["bodyValues"]["html"] == {"value": "<p>hi</p>"}

    def test_send_falls_back_to_inbox_mailbox(self, fake, get_tool_fn, with_key, monkeypatch):
        monkeypatch.setitem(MAILBOXES, "sent", None)
        get_tool_fn("atomicmail_send")(to="a@example.com", subject="Hi", body="text")
        draft = fake.jmap_envelopes[-1]["methodCalls"][0][1]["create"]["d1"]
        assert draft["mailboxIds"] == {"mb-inbox": True}

    @pytest.mark.parametrize(
        "kwargs,error",
        [
            ({"to": "not-an-address", "subject": "s", "body": "b"}, "Invalid recipient"),
            ({"to": "", "subject": "s", "body": "b"}, "Invalid recipient"),
            ({"to": "a@b.com", "subject": "s", "body": "b", "cc": "bad"}, "Invalid CC"),
            ({"to": "a@b.com", "subject": " ", "body": "b"}, "subject cannot be empty"),
            ({"to": "a@b.com", "subject": "s", "body": ""}, "body cannot be empty"),
        ],
    )
    def test_send_validation(self, fake, get_tool_fn, with_key, kwargs, error):
        result = get_tool_fn("atomicmail_send")(**kwargs)
        assert error in result["error"]
        assert fake.calls["jmap"] == 0

    def test_send_not_created(self, fake, get_tool_fn, with_key):
        def handler(name, args, cid):
            if name == "Email/set":
                return {"notCreated": {"d1": {"type": "forbiddenFrom"}}}
            if name == "EmailSubmission/set":
                return {"notCreated": {"s1": {"type": "invalidProperties"}}}
            return fake.default_jmap_handler(name, args, cid)

        fake.jmap_handler = handler
        result = get_tool_fn("atomicmail_send")(to="a@b.com", subject="s", body="b")
        assert "forbiddenFrom" in result["error"]

    def test_submission_not_created(self, fake, get_tool_fn, with_key):
        def handler(name, args, cid):
            if name == "EmailSubmission/set":
                return {"notCreated": {"s1": {"type": "tooManyRecipients"}}}
            return fake.default_jmap_handler(name, args, cid)

        fake.jmap_handler = handler
        result = get_tool_fn("atomicmail_send")(to="a@b.com", subject="s", body="b")
        assert "could not be sent" in result["error"]
        assert "tooManyRecipients" in result["error"]


class TestReply:
    def _original(self, **overrides):
        email = {
            "id": "e1",
            "from": [{"name": "Alice", "email": "alice@example.com"}],
            "replyTo": [{"email": "replies@example.com"}],
            "subject": "Your\n  signup",
            "messageId": ["<m1@example.com>"],
            "references": ["<m0@example.com>"],
        }
        email.update(overrides)
        return email

    def _use_original(self, fake, original):
        def handler(name, args, cid):
            if name == "Email/get":
                return {"list": [original] if original else [], "notFound": [] if original else args["ids"]}
            return fake.default_jmap_handler(name, args, cid)

        fake.jmap_handler = handler

    def test_reply_threads_and_prefers_reply_to(self, fake, get_tool_fn, with_key):
        self._use_original(fake, self._original())
        result = get_tool_fn("atomicmail_reply")(email_id="e1", body="Thanks!")
        assert result["success"] is True
        assert result["to"] == "replies@example.com"
        assert result["subject"] == "Re: Your signup"

        draft = fake.jmap_envelopes[-1]["methodCalls"][0][1]["create"]["d1"]
        assert draft["inReplyTo"] == ["<m1@example.com>"]
        assert draft["references"] == ["<m0@example.com>", "<m1@example.com>"]
        assert draft["to"] == [{"email": "replies@example.com"}]

    def test_reply_falls_back_to_from_and_keeps_re(self, fake, get_tool_fn, with_key):
        self._use_original(fake, self._original(replyTo=None, subject="RE: hi", references=None))
        result = get_tool_fn("atomicmail_reply")(email_id="e1", body="ok")
        assert result["to"] == "alice@example.com"
        assert result["subject"] == "RE: hi"
        draft = fake.jmap_envelopes[-1]["methodCalls"][0][1]["create"]["d1"]
        assert draft["references"] == ["<m1@example.com>"]

    def test_reply_not_found(self, fake, get_tool_fn, with_key):
        self._use_original(fake, None)
        result = get_tool_fn("atomicmail_reply")(email_id="missing", body="ok")
        assert result["error"] == "Email 'missing' not found"

    def test_reply_without_address(self, fake, get_tool_fn, with_key):
        self._use_original(fake, self._original(replyTo=None, **{"from": None}))
        result = get_tool_fn("atomicmail_reply")(email_id="e1", body="ok")
        assert "no address" in result["error"]


# ============================================================================
# List / read / search / mark read
# ============================================================================


class TestReadTools:
    def test_list_emails(self, fake, get_tool_fn, with_key):
        def handler(name, args, cid):
            if name == "Email/get":
                return {
                    "list": [
                        {
                            "id": "e1",
                            "threadId": "t1",
                            "receivedAt": "2026-11-01T10:00:00Z",
                            "from": [{"name": "Bob", "email": "bob@example.com"}],
                            "to": [{"email": "my-agent@atomicmail.ai"}],
                            "subject": "Hi",
                            "preview": "Hello...",
                            "keywords": {"$seen": True},
                        }
                    ]
                }
            return fake.default_jmap_handler(name, args, cid)

        fake.jmap_handler = handler
        result = get_tool_fn("atomicmail_list_emails")(limit=500, unread_only=True)
        assert result["mailbox"] == "inbox"
        assert result["count"] == 1
        assert result["emails"][0] == {
            "id": "e1",
            "thread_id": "t1",
            "received_at": "2026-11-01T10:00:00Z",
            "from": ["Bob <bob@example.com>"],
            "to": ["my-agent@atomicmail.ai"],
            "subject": "Hi",
            "preview": "Hello...",
            "is_read": True,
        }
        query_args = next(args for name, args, _ in fake.method_calls() if name == "Email/query")
        assert query_args["filter"] == {"inMailbox": "mb-inbox", "notKeyword": "$seen"}
        assert query_args["limit"] == 100
        get_args = next(args for name, args, _ in fake.method_calls() if name == "Email/get")
        assert get_args["#ids"] == {"resultOf": "q0", "name": "Email/query", "path": "/ids"}

    def test_mailbox_ids_cached(self, fake, get_tool_fn, with_key):
        get_tool_fn("atomicmail_list_emails")()
        get_tool_fn("atomicmail_list_emails")()
        assert sum(1 for name, _, _ in fake.method_calls() if name == "Mailbox/query") == 1

    def test_list_unknown_mailbox(self, fake, get_tool_fn, with_key):
        result = get_tool_fn("atomicmail_list_emails")(mailbox="spam-folder")
        assert "Unknown mailbox" in result["error"]

    def test_list_missing_mailbox(self, fake, get_tool_fn, with_key):
        result = get_tool_fn("atomicmail_list_emails")(mailbox="trash")
        assert result["error"] == "This account has no 'trash' mailbox"

    def test_read_email_text(self, fake, get_tool_fn, with_key):
        def handler(name, args, cid):
            assert args["fetchTextBodyValues"] is True
            assert args["maxBodyValueBytes"] > 0
            return {
                "list": [
                    {
                        "id": "e1",
                        "subject": "Code",
                        "messageId": ["<m1@x>"],
                        "from": [{"email": "noreply@saas.example"}],
                        "cc": [],
                        "keywords": {},
                        "textBody": [{"partId": "1"}, {"partId": "2"}],
                        "htmlBody": [{"partId": "3"}],
                        "bodyValues": {
                            "1": {"value": "Your code is 123456", "isTruncated": False},
                            "2": {"value": "Footer", "isTruncated": True},
                            "3": {"value": "<p>ignored</p>"},
                        },
                        "attachments": [{"name": "a.pdf", "type": "application/pdf", "size": 10, "blobId": "b1"}],
                    }
                ]
            }

        fake.jmap_handler = handler
        result = get_tool_fn("atomicmail_read_email")(email_id="e1")
        assert result["success"] is True
        assert result["text"] == "Your code is 123456\nFooter"
        assert result["truncated"] is True
        assert result["message_id"] == "<m1@x>"
        assert result["from"] == ["noreply@saas.example"]
        assert result["is_read"] is False
        assert "html" not in result
        assert "preview" not in result
        assert result["attachments"] == [{"name": "a.pdf", "type": "application/pdf", "size": 10, "blob_id": "b1"}]

    def test_read_email_html_only(self, fake, get_tool_fn, with_key):
        fake.jmap_handler = lambda name, args, cid: {
            "list": [{"id": "e1", "textBody": [], "htmlBody": [{"partId": "h"}], "bodyValues": {"h": {"value": "<b>hi</b>"}}}]
        }
        result = get_tool_fn("atomicmail_read_email")(email_id="e1")
        assert result["text"] == ""
        assert result["html"] == "<b>hi</b>"
        assert "truncated" not in result

    def test_read_email_not_found(self, fake, get_tool_fn, with_key):
        fake.jmap_handler = lambda name, args, cid: {"list": [], "notFound": ["e9"]}
        assert get_tool_fn("atomicmail_read_email")(email_id="e9") == {"error": "Email 'e9' not found"}

    def test_search(self, fake, get_tool_fn, with_key):
        result = get_tool_fn("atomicmail_search")(query="  verification code ", limit=5)
        assert result["query"] == "verification code"
        assert result["count"] == 1
        query_args = next(args for name, args, _ in fake.method_calls() if name == "Email/query")
        assert query_args["filter"] == {"text": "verification code"}
        assert query_args["limit"] == 5

    def test_search_empty_query(self, fake, get_tool_fn, with_key):
        assert "cannot be empty" in get_tool_fn("atomicmail_search")(query=" ")["error"]

    def test_mark_read_and_unread(self, fake, get_tool_fn, with_key):
        result = get_tool_fn("atomicmail_mark_read")(email_ids="e1, e2")
        assert result == {"success": True, "updated": ["e1", "e2"], "failed": {}}
        update = fake.method_calls()[-1][1]["update"]
        assert update == {"e1": {"keywords/$seen": True}, "e2": {"keywords/$seen": True}}

        get_tool_fn("atomicmail_mark_read")(email_ids="e1", read=False)
        assert fake.method_calls()[-1][1]["update"] == {"e1": {"keywords/$seen": None}}

    def test_mark_read_partial_failure(self, fake, get_tool_fn, with_key):
        fake.jmap_handler = lambda name, args, cid: {"updated": {"e1": None}, "notUpdated": {"e2": {"type": "notFound"}}}
        result = get_tool_fn("atomicmail_mark_read")(email_ids="e1,e2")
        assert result == {"success": False, "updated": ["e1"], "failed": {"e2": "notFound"}}


# ============================================================================
# Transport-level behaviour
# ============================================================================


class TestTransport:
    def test_jmap_401_retries_with_fresh_capability(self, fake, get_tool_fn, with_key):
        fake.jmap_status = [401]
        result = get_tool_fn("atomicmail_search")(query="x")
        assert result["count"] == 1
        assert fake.calls["capability"] == 2
        assert fake.calls["challenge"] == 1

    def test_jmap_rate_limited(self, fake, get_tool_fn, with_key):
        fake.jmap_status = [429]
        assert get_tool_fn("atomicmail_search")(query="x")["error"] == "Rate limit exceeded. Try again later."

    def test_jmap_method_error(self, fake, get_tool_fn, with_key):
        def post(url, **kwargs):
            if url == JMAP_URL:
                body = {"methodResponses": [["error", {"type": "unknownMethod", "description": "nope"}, "q0"]]}
                return _response(200, url, json_body=body)
            return fake.post(url, **kwargs)

        with patch("httpx.post", side_effect=post):
            result = get_tool_fn("atomicmail_search")(query="x")
        assert result["error"] == "JMAP error in 'q0': unknownMethod nope"

    def test_timeout(self, get_tool_fn, with_key):
        with patch("httpx.post", side_effect=httpx.TimeoutException("slow")):
            assert get_tool_fn("atomicmail_search")(query="x") == {"error": "Request timed out"}

    def test_network_error(self, get_tool_fn, with_key):
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            assert "Network error" in get_tool_fn("atomicmail_get_address")()["error"]


# ============================================================================
# Health checker
# ============================================================================


class TestHealthChecker:
    def test_valid_key(self, fake):
        result = AtomicMailHealthChecker().check("test-key")
        assert result.valid is True
        assert result.details["identity"] == {"email": "my-agent@atomicmail.ai"}

    def test_invalid_key(self, fake):
        result = AtomicMailHealthChecker().check("wrong-key")
        assert result.valid is False
        assert result.message == "Atomic Mail API key is invalid"
        assert result.details["status_code"] == 401

    def test_timeout(self):
        with patch("httpx.post", side_effect=httpx.TimeoutException("slow")):
            result = AtomicMailHealthChecker().check("k")
        assert result.valid is False
        assert result.details == {"error": "timeout"}
