"""
Atomic Mail Tool - give an agent its own email inbox (@atomicmail.ai).

The agent sends, reads, searches and replies through JMAP (RFC 8620/8621).
Authentication (proof-of-work login, short-lived tokens) lives in ``auth.py``.

Supports:
- API key authentication (ATOMIC_MAIL_API_KEY)

Docs: https://docs.atomicmail.ai
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

from .auth import REQUEST_TIMEOUT_S, AtomicMailAuthError, AtomicMailSession

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

JMAP_CORE = "urn:ietf:params:jmap:core"
JMAP_MAIL = "urn:ietf:params:jmap:mail"
JMAP_SUBMISSION = "urn:ietf:params:jmap:submission"
MAIL_USING = [JMAP_CORE, JMAP_MAIL]
SEND_USING = [JMAP_CORE, JMAP_MAIL, JMAP_SUBMISSION]

SUMMARY_PROPERTIES = ["id", "threadId", "receivedAt", "from", "to", "subject", "preview", "keywords"]
DETAIL_PROPERTIES = [
    "id",
    "threadId",
    "messageId",
    "receivedAt",
    "from",
    "to",
    "cc",
    "replyTo",
    "subject",
    "keywords",
    "textBody",
    "htmlBody",
    "bodyValues",
    "attachments",
]
# Standard JMAP mailbox roles (RFC 8621 / RFC 8457) an agent may list.
MAILBOX_ROLES = {"inbox", "sent", "drafts", "trash", "junk", "archive"}
MAX_LIST_LIMIT = 100
# Cap on body text returned per part, to keep large emails out of the context window.
MAX_BODY_BYTES = 100_000

API_KEY_HELP = (
    "Set the ATOMIC_MAIL_API_KEY environment variable or configure it via the credential store. "
    "Register an agent inbox and get its API key at https://docs.atomicmail.ai"
)


class AtomicMailError(Exception):
    """A JMAP request was refused or a method call failed."""


def _format_addresses(addresses: list[dict[str, Any]] | None) -> list[str]:
    """Render JMAP EmailAddress objects as ``Name <email>`` strings."""
    out = []
    for addr in addresses or []:
        email, name = addr.get("email") or "", addr.get("name")
        out.append(f"{name} <{email}>" if name else email)
    return out


def _summarize(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": email.get("id"),
        "thread_id": email.get("threadId"),
        "received_at": email.get("receivedAt"),
        "from": _format_addresses(email.get("from")),
        "to": _format_addresses(email.get("to")),
        "subject": email.get("subject"),
        "preview": email.get("preview"),
        "is_read": bool((email.get("keywords") or {}).get("$seen")),
    }


def _join_parts(parts: list[dict[str, Any]] | None, values: dict[str, Any]) -> tuple[str, bool]:
    """Concatenate the fetched values of body parts; report truncation."""
    texts, truncated = [], False
    for part in parts or []:
        value = values.get(part.get("partId") or "")
        if value:
            texts.append(value.get("value", ""))
            truncated = truncated or bool(value.get("isTruncated"))
    return "\n".join(texts), truncated


def _parse_recipients(raw: str) -> list[str] | None:
    """Split a comma-separated recipient list; None if any entry is invalid."""
    recipients = [r.strip() for r in raw.split(",") if r.strip()]
    if not recipients or any("@" not in r for r in recipients):
        return None
    return recipients


class _AtomicMailClient:
    """JMAP operations against one agent inbox."""

    def __init__(self, session: AtomicMailSession):
        self.session = session

    def call(self, method_calls: list[list[Any]], using: list[str] | None = None) -> dict[str, Any]:
        """POST a JMAP request; return method-call id -> response arguments.

        Retries once on 401 because the 2-minute capability token can expire
        between minting and use.
        """
        envelope = {"using": using or MAIL_USING, "methodCalls": method_calls}
        response: httpx.Response | None = None
        for attempt in range(2):
            token = self.session.capability_token()
            response = httpx.post(
                self.session.jmap_api_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=envelope,
                timeout=REQUEST_TIMEOUT_S,
            )
            if response.status_code != 401 or attempt == 1:
                break
            self.session.invalidate_capability()

        assert response is not None
        if response.status_code == 429:
            raise AtomicMailError("Rate limit exceeded. Try again later.")
        if not response.is_success:
            raise AtomicMailError(f"JMAP request failed: HTTP {response.status_code}: {response.text[:500]}")

        results: dict[str, Any] = {}
        for name, args, call_id in response.json().get("methodResponses", []):
            if name == "error":
                detail = args.get("description") or ""
                raise AtomicMailError(f"JMAP error in '{call_id}': {args.get('type', 'unknown')} {detail}".strip())
            results[call_id] = args
        return results

    def mailbox_id(self, role: str) -> str | None:
        """Resolve a mailbox id by role (cached on the session)."""
        cached = self.session.mailbox_ids.get(role)
        if cached:
            return cached
        res = self.call([["Mailbox/query", {"accountId": self.session.account_id, "filter": {"role": role}}, "mq0"]])
        ids = res.get("mq0", {}).get("ids") or []
        if not ids:
            return None
        self.session.mailbox_ids[role] = ids[0]
        return ids[0]

    def query_emails(self, filter_: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        """Email/query newest first, then Email/get the summary properties."""
        account_id = self.session.account_id
        res = self.call(
            [
                [
                    "Email/query",
                    {
                        "accountId": account_id,
                        "filter": filter_,
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": limit,
                    },
                    "q0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {"resultOf": "q0", "name": "Email/query", "path": "/ids"},
                        "properties": SUMMARY_PROPERTIES,
                    },
                    "g0",
                ],
            ]
        )
        return res.get("g0", {}).get("list", [])

    def get_email(self, email_id: str, properties: list[str] | None = None) -> dict[str, Any] | None:
        args: dict[str, Any] = {
            "accountId": self.session.account_id,
            "ids": [email_id],
            "properties": properties or DETAIL_PROPERTIES,
        }
        if properties is None:
            args.update(fetchTextBodyValues=True, fetchHTMLBodyValues=True, maxBodyValueBytes=MAX_BODY_BYTES)
        found = self.call([["Email/get", args, "g0"]]).get("g0", {}).get("list") or []
        return found[0] if found else None

    def send(
        self,
        to: list[str],
        subject: str,
        text: str,
        *,
        html: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: list[str] | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create the message in Sent and submit it (Email/set + EmailSubmission/set)."""
        # The address comes from the capability token's inboxId claim, so make
        # sure one has been minted (a fresh session has none yet).
        self.session.capability_token()
        sender = self.session.inbox_address
        if not sender:
            raise AtomicMailError("Could not determine this agent's inbox address from the capability token")
        # Reference client falls back to the inbox when no Sent mailbox exists.
        mailbox = self.mailbox_id("sent") or self.mailbox_id("inbox")
        if not mailbox:
            raise AtomicMailError("No Sent or Inbox mailbox found for this account")

        draft: dict[str, Any] = {
            "mailboxIds": {mailbox: True},
            "from": [{"email": sender}],
            "to": [{"email": r} for r in to],
            "subject": subject,
            "textBody": [{"partId": "text", "type": "text/plain"}],
            "bodyValues": {"text": {"value": text}},
            "keywords": {"$draft": True, "$seen": True},
        }
        if html:
            # Giving both textBody and htmlBody makes the server build multipart/alternative.
            draft["htmlBody"] = [{"partId": "html", "type": "text/html"}]
            draft["bodyValues"]["html"] = {"value": html}
        if cc:
            draft["cc"] = [{"email": r} for r in cc]
        if in_reply_to:
            draft["inReplyTo"] = in_reply_to
        if references:
            draft["references"] = references

        account_id = self.session.account_id
        res = self.call(
            [
                ["Email/set", {"accountId": account_id, "create": {"d1": draft}}, "c0"],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": account_id,
                        "onSuccessUpdateEmail": {"#s1": {"keywords/$draft": None, "keywords/$sent": True}},
                        "create": {
                            "s1": {
                                "emailId": "#d1",
                                "envelope": {
                                    "mailFrom": {"email": sender},
                                    "rcptTo": [{"email": r} for r in to + (cc or [])],
                                },
                            }
                        },
                    },
                    "c1",
                ],
            ],
            using=SEND_USING,
        )
        not_created = res.get("c0", {}).get("notCreated") or {}
        if "d1" in not_created:
            raise AtomicMailError(f"Email could not be created: {not_created['d1']}")
        not_submitted = res.get("c1", {}).get("notCreated") or {}
        if "s1" in not_submitted:
            raise AtomicMailError(f"Email could not be sent: {not_submitted['s1']}")
        return {
            "email_id": (res.get("c0", {}).get("created") or {}).get("d1", {}).get("id"),
            "submission_id": (res.get("c1", {}).get("created") or {}).get("s1", {}).get("id"),
            "from": sender,
        }

    def set_seen(self, email_ids: list[str], seen: bool) -> dict[str, Any]:
        # Patch syntax: setting a keyword path to null removes it (RFC 8620 5.3).
        patch = {"keywords/$seen": True if seen else None}
        res = self.call([["Email/set", {"accountId": self.session.account_id, "update": dict.fromkeys(email_ids, patch)}, "u0"]])
        return res.get("u0", {})


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Atomic Mail tools with the MCP server."""

    # One session per API key, so the PoW login and tokens survive across tool calls.
    sessions: dict[str, AtomicMailSession] = {}
    sessions_lock = threading.Lock()

    def _get_api_key() -> str | None:
        if credentials is not None:
            key = credentials.get("atomicmail")
            if key is not None and not isinstance(key, str):
                raise TypeError(f"Expected string from credentials, got {type(key).__name__}")
            return key
        return os.getenv("ATOMIC_MAIL_API_KEY")

    def _get_client() -> _AtomicMailClient | dict[str, str]:
        api_key = _get_api_key()
        if not api_key:
            return {"error": "Atomic Mail credentials not configured", "help": API_KEY_HELP}
        with sessions_lock:
            session = sessions.get(api_key)
            if session is None:
                session = sessions[api_key] = AtomicMailSession(api_key)
        return _AtomicMailClient(session)

    def _run(action: Callable[[_AtomicMailClient], dict[str, Any]]) -> dict[str, Any]:
        """Resolve the client, run ``action``, and map failures to error dicts."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return action(client)
        except AtomicMailAuthError as e:
            result: dict[str, Any] = {"error": str(e)}
            if e.hint:
                result["help"] = e.hint
            return result
        except AtomicMailError as e:
            return {"error": str(e)}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def atomicmail_get_address() -> dict:
        """
        Get this agent's own Atomic Mail email address.

        Use it when signing up for a service or telling someone where to reply.

        Returns:
            Dict with the inbox email address or error
        """

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            client.session.capability_token()
            address = client.session.inbox_address
            if not address:
                return {"error": "Atomic Mail did not report an inbox address for this API key"}
            return {"success": True, "address": address}

        return _run(action)

    @mcp.tool()
    def atomicmail_send(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        html_body: str = "",
    ) -> dict:
        """
        Send an email from this agent's Atomic Mail inbox.

        Args:
            to: Recipient address, or several separated by commas
            subject: Email subject line
            body: Plain-text body
            cc: Optional CC addresses, separated by commas
            html_body: Optional HTML version of the body

        Returns:
            Dict with the sent email's id and sender address, or error
        """
        recipients = _parse_recipients(to)
        cc_list = _parse_recipients(cc) if cc.strip() else []

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            if recipients is None:
                return {"error": "Invalid recipient email address"}
            if cc_list is None:
                return {"error": "Invalid CC email address"}
            if not subject.strip():
                return {"error": "Email subject cannot be empty"}
            if not body.strip():
                return {"error": "Email body cannot be empty"}
            sent = client.send(recipients, subject, body, html=html_body or None, cc=cc_list)
            return {"success": True, **sent}

        return _run(action)

    @mcp.tool()
    def atomicmail_list_emails(
        mailbox: str = "inbox",
        limit: int = 20,
        unread_only: bool = False,
    ) -> dict:
        """
        List recent emails in a mailbox, newest first.

        Args:
            mailbox: Mailbox role: 'inbox', 'sent', 'drafts', 'trash', 'junk' or 'archive' (default 'inbox')
            limit: Maximum number of emails to return (1-100, default 20)
            unread_only: Only return emails not yet marked as read

        Returns:
            Dict with email summaries (id, from, subject, preview, is_read) or error
        """

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            role = mailbox.strip().lower()
            if role not in MAILBOX_ROLES:
                return {"error": f"Unknown mailbox '{mailbox}'. Use one of: {', '.join(sorted(MAILBOX_ROLES))}"}
            mailbox_id = client.mailbox_id(role)
            if not mailbox_id:
                return {"error": f"This account has no '{role}' mailbox"}
            filter_: dict[str, Any] = {"inMailbox": mailbox_id}
            if unread_only:
                filter_["notKeyword"] = "$seen"
            emails = client.query_emails(filter_, max(1, min(limit, MAX_LIST_LIMIT)))
            return {"mailbox": role, "count": len(emails), "emails": [_summarize(e) for e in emails]}

        return _run(action)

    @mcp.tool()
    def atomicmail_read_email(email_id: str) -> dict:
        """
        Read one email in full: headers, body text and attachment list.

        Args:
            email_id: Email id from atomicmail_list_emails or atomicmail_search

        Returns:
            Dict with the email's headers, text body and attachments, or error
        """

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            if not email_id.strip():
                return {"error": "email_id cannot be empty"}
            email = client.get_email(email_id.strip())
            if email is None:
                return {"error": f"Email '{email_id}' not found"}
            values = email.get("bodyValues") or {}
            text, text_truncated = _join_parts(email.get("textBody"), values)
            result = {
                "success": True,
                **_summarize(email),
                "message_id": (email.get("messageId") or [None])[0],
                "cc": _format_addresses(email.get("cc")),
                "reply_to": _format_addresses(email.get("replyTo")),
                "text": text,
                "attachments": [
                    {"name": a.get("name"), "type": a.get("type"), "size": a.get("size"), "blob_id": a.get("blobId")}
                    for a in email.get("attachments") or []
                ],
            }
            result.pop("preview", None)
            truncated = text_truncated
            if not text:
                # HTML-only message: return the HTML so the content is not lost.
                result["html"], truncated = _join_parts(email.get("htmlBody"), values)
            if truncated:
                result["truncated"] = True
            return result

        return _run(action)

    @mcp.tool()
    def atomicmail_search(query: str, limit: int = 20) -> dict:
        """
        Full-text search across all emails in this agent's inbox (subject, body and addresses).

        Args:
            query: Text to search for, e.g. 'verification code'
            limit: Maximum number of results (1-100, default 20)

        Returns:
            Dict with matching email summaries, newest first, or error
        """

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            if not query.strip():
                return {"error": "Search query cannot be empty"}
            emails = client.query_emails({"text": query.strip()}, max(1, min(limit, MAX_LIST_LIMIT)))
            return {"query": query.strip(), "count": len(emails), "emails": [_summarize(e) for e in emails]}

        return _run(action)

    @mcp.tool()
    def atomicmail_reply(email_id: str, body: str) -> dict:
        """
        Reply to an email in the same thread.

        The reply goes to the original's Reply-To address (or its sender), with
        'Re:' prefixed to the subject and threading headers set.

        Args:
            email_id: Id of the email being replied to
            body: Plain-text reply body

        Returns:
            Dict with the sent reply's id and recipient, or error
        """

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            if not email_id.strip():
                return {"error": "email_id cannot be empty"}
            if not body.strip():
                return {"error": "Reply body cannot be empty"}
            original = client.get_email(
                email_id.strip(),
                properties=["from", "replyTo", "sender", "subject", "messageId", "references"],
            )
            if original is None:
                return {"error": f"Email '{email_id}' not found"}
            recipient = next(
                (
                    addrs[0]["email"]
                    for addrs in (original.get("replyTo"), original.get("from"), original.get("sender"))
                    if addrs and addrs[0].get("email")
                ),
                None,
            )
            if not recipient:
                return {"error": "Original email has no address to reply to"}
            subject = " ".join((original.get("subject") or "").split())
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}".strip()
            message_ids = original.get("messageId") or []
            references = (original.get("references") or []) + message_ids
            sent = client.send(
                [recipient],
                subject,
                body,
                in_reply_to=message_ids or None,
                references=references or None,
            )
            return {"success": True, "to": recipient, "subject": subject, **sent}

        return _run(action)

    @mcp.tool()
    def atomicmail_mark_read(email_ids: str, read: bool = True) -> dict:
        """
        Mark emails as read, or as unread with read=False.

        Args:
            email_ids: One email id, or several separated by commas
            read: True to mark as read (default), False to mark as unread

        Returns:
            Dict listing updated ids and any that failed, or error
        """
        ids = [i.strip() for i in email_ids.split(",") if i.strip()]

        def action(client: _AtomicMailClient) -> dict[str, Any]:
            if not ids:
                return {"error": "email_ids cannot be empty"}
            res = client.set_seen(ids, read)
            failed = res.get("notUpdated") or {}
            return {
                "success": not failed,
                "updated": [i for i in ids if i in (res.get("updated") or {})],
                "failed": {i: (err or {}).get("type", "unknown") for i, err in failed.items()},
            }

        return _run(action)
