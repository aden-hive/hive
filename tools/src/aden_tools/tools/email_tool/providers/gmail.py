"""
Gmail provider for the Unified Email Tool Base.

Ports the existing httpx-based Gmail API logic from the old email_tool.py
into the new BaseEmailProvider interface map.
"""

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
from typing import TYPE_CHECKING, Any

import httpx

from aden_tools.tools.email_tool.base import BaseEmailProvider
from aden_tools.tools.email_tool.schemas import (
    AttachmentMetadata,
    EmailFolder,
    EmailListRequest,
    EmailListResponse,
    EmailMessageDetail,
    EmailMessageSummary,
    EmailReadRequest,
    EmailReadResponse,
    EmailSearchRequest,
    EmailSearchResponse,
    EmailSendRequest,
    EmailSendResponse,
)

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class GmailEmailProvider(BaseEmailProvider):
    """
    Gmail implementation of the Email Provider interface.
    
    Uses standard HTTP calls to the Gmail API (https://gmail.googleapis.com).
    """

    def __init__(self, credentials: "CredentialStoreAdapter | None" = None, account_alias: str = ""):
        self.credentials = credentials
        self.account_alias = account_alias

    @property
    def provider_id(self) -> str:
        return "gmail"

    def _get_access_token(self) -> str:
        """Retrieves the access token from the environment or credential store."""
        if self.credentials:
            if self.account_alias:
                token = self.credentials.get_by_alias("google", self.account_alias)
                if token:
                    return token
            token = self.credentials.get("google")
            if token:
                return token
        token = os.getenv("GOOGLE_ACCESS_TOKEN")
        if token:
            return token
        raise ValueError("Google access token missing. Please authenticate via Hive credentials.")

    def _make_auth_header(self) -> dict[str, str]:
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # -------------------------------------------------------------------------
    # Send
    # -------------------------------------------------------------------------

    def send_email(self, req: EmailSendRequest) -> EmailSendResponse:
        """Send a new email or reply if reply_to_message_id is present."""
        try:
            headers = self._make_auth_header()
        except ValueError as e:
            return EmailSendResponse(success=False, provider=self.provider_id, error=str(e))

        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(req.to)
        msg["Subject"] = req.subject
        if req.from_email:
            msg["From"] = req.from_email
        if req.cc:
            msg["Cc"] = ", ".join(req.cc)
        if req.bcc:
            msg["Bcc"] = ", ".join(req.bcc)

        # Threading support
        thread_id = None
        if req.reply_to_message_id:
            # We must fetch the original to grab headers
            try:
                original = self._fetch_original_message_headers(headers, req.reply_to_message_id)
                thread_id = original.get("threadId")
                orig_message_id = original.get("Message-ID")
                
                if orig_message_id:
                    msg["In-Reply-To"] = orig_message_id
                    msg["References"] = orig_message_id
                    
                # Fix up the topic if it doesn't have Re:
                if not req.subject.lower().startswith("re:"):
                    msg.replace_header("Subject", f"Re: {req.subject}")
            except Exception as e:
                # Failing to fetch headers shouldn't completely crash a send if not vital,
                # but for threading it breaks the chain so we return an error.
                return EmailSendResponse(success=False, provider=self.provider_id, error=f"Failed to fetch original message for reply: {e}")

        if req.body_html:
            msg.attach(MIMEText(req.body_html, "html"))
        elif req.body_text:
            msg.attach(MIMEText(req.body_text, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        payload: dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id

        try:
            resp = httpx.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            
            if resp.status_code == 401:
                return EmailSendResponse(success=False, provider=self.provider_id, error="Gmail token expired or invalid. Please re-authorize via Hive.")
            if resp.status_code != 200:
                return EmailSendResponse(success=False, provider=self.provider_id, error=f"Gmail API error (HTTP {resp.status_code}): {resp.text}")

            data = resp.json()
            return EmailSendResponse(
                success=True,
                message_id=data.get("id"),
                thread_id=data.get("threadId"),
                provider=self.provider_id
            )
        except Exception as e:
            return EmailSendResponse(success=False, provider=self.provider_id, error=f"Request failed: {str(e)}")

    def _fetch_original_message_headers(self, headers: dict[str, str], message_id: str) -> dict[str, str]:
        """Fetch threading required headers for a specific message ID."""
        resp = httpx.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers=headers,
            params={"format": "metadata", "metadataHeaders": ["Message-ID", "Subject", "From"]},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        out = {"threadId": data.get("threadId")}
        for header in data.get("payload", {}).get("headers", []):
            if header["name"].lower() == "message-id":
                out["Message-ID"] = header["value"]
        return out

    # -------------------------------------------------------------------------
    # List & Search
    # -------------------------------------------------------------------------

    def _execute_query(self, query: str, limit: int) -> list[EmailMessageSummary]:
        """Generic query executor for both list and search methods."""
        headers = self._make_auth_header()
        
        # Step 1: Fetch message IDs matching the query
        params: dict[str, Any] = {"q": query, "maxResults": limit}
        
        resp = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        messages_meta = resp.json().get("messages", [])
        
        if not messages_meta:
            return []

        # Step 2: In a real production system we should batch-fetch metadata. 
        # For phase 1, we map sequentially, but in subsequent PRs a batch request is better.
        summaries = []
        for meta in messages_meta:
            m_id = meta["id"]
            # Fetch snippet and headers only to save bandwidth
            detail_resp = httpx.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m_id}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},
                timeout=15.0,
            )
            detail_resp.raise_for_status()
            d_json = detail_resp.json()
            
            p_headers = {h["name"].lower(): h["value"] for h in d_json.get("payload", {}).get("headers", [])}
            
            # Simple placeholder mapping for datetime (leaving parsing up to further iteration)
            to_list = [addr.strip() for addr in p_headers.get("to", "").split(",") if addr.strip()]
            
            summaries.append(EmailMessageSummary(
                message_id=m_id,
                thread_id=d_json.get("threadId"),
                subject=p_headers.get("subject", "(No Subject)"),
                sender=p_headers.get("from", "Unknown"),
                to=to_list,
                unread="UNREAD" in d_json.get("labelIds", []),
                snippet=d_json.get("snippet"),
                folders=d_json.get("labelIds", []),
                has_attachments=False, # We don't know without the payload, fake as false for summary
                provider=self.provider_id
            ))
            
        return summaries

    def list_emails(self, req: EmailListRequest) -> EmailListResponse:
        try:
            # Build Gmail native query
            q_parts = []
            if req.folder:
                q_parts.append(f"label:{req.folder}")
            if req.unread_only:
                q_parts.append("is:unread")
                
            query = " ".join(q_parts)
            
            summaries = self._execute_query(query, req.limit)
            return EmailListResponse(messages=summaries, provider=self.provider_id)
            
        except Exception as e:
            return EmailListResponse(messages=[], provider=self.provider_id, error=str(e))

    def search_emails(self, req: EmailSearchRequest) -> EmailSearchResponse:
        try:
            # Translate normalized search to Gmail query
            q_parts = []
            if req.query:
                q_parts.append(req.query)
            if req.sender:
                q_parts.append(f"from:{req.sender}")
            if req.subject_contains:
                q_parts.append(f"subject:{req.subject_contains}")
            if req.folder:
                q_parts.append(f"label:{req.folder}")
            if req.unread_only is True:
                q_parts.append("is:unread")
            elif req.unread_only is False:
                q_parts.append("is:read")
            if req.date_from:
                q_parts.append(f"after:{int(req.date_from.timestamp())}")
            if req.date_to:
                q_parts.append(f"before:{int(req.date_to.timestamp())}")

            query = " ".join(q_parts)
            
            summaries = self._execute_query(query, req.limit)
            return EmailSearchResponse(messages=summaries, provider=self.provider_id)
            
        except Exception as e:
            return EmailSearchResponse(messages=[], provider=self.provider_id, error=str(e))

    # -------------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------------

    def read_email(self, req: EmailReadRequest) -> EmailReadResponse:
        try:
            headers = self._make_auth_header()
            
            resp = httpx.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{req.message_id}",
                headers=headers,
                params={"format": "full"},
                timeout=30.0,
            )
            
            if resp.status_code == 404:
                return EmailReadResponse(provider=self.provider_id, error="Email not found.")
            resp.raise_for_status()
            
            data = resp.json()
            p_headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
            to_list = [addr.strip() for addr in p_headers.get("to", "").split(",") if addr.strip()]
            cc_list = [addr.strip() for addr in p_headers.get("cc", "").split(",") if addr.strip()]
            bcc_list = [addr.strip() for addr in p_headers.get("bcc", "").split(",") if addr.strip()]

            # Decode body parts (Simplified extraction for text/plain and text/html)
            body_text = None
            body_html = None
            attachments = []
            
            def extract_parts(parts: list[dict]):
                nonlocal body_text, body_html
                for part in parts:
                    mime_type = part.get("mimeType")
                    body_data = part.get("body", {}).get("data")
                    
                    if mime_type == "text/plain" and body_data:
                        body_text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                    elif mime_type == "text/html" and body_data:
                        body_html = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                    elif mime_type and mime_type.startswith("multipart/"):
                        extract_parts(part.get("parts", []))
                    elif part.get("filename"):
                        # Attachment
                        if req.include_attachments_metadata:
                            attachments.append(AttachmentMetadata(
                                id=part["body"].get("attachmentId", ""),
                                filename=part["filename"],
                                content_type=mime_type or "application/octet-stream",
                                size_bytes=part["body"].get("size")
                            ))

            # Handle single-part vs multi-part payload
            payload = data.get("payload", {})
            if payload.get("parts"):
                extract_parts(payload["parts"])
            else:
                mime_type = payload.get("mimeType")
                body_data = payload.get("body", {}).get("data")
                if mime_type == "text/plain" and body_data:
                    body_text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                elif mime_type == "text/html" and body_data:
                    body_html = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            
            if not req.include_body_html:
                body_html = None

            detail = EmailMessageDetail(
                message_id=data["id"],
                thread_id=data.get("threadId"),
                subject=p_headers.get("subject", "(No Subject)"),
                sender=p_headers.get("from", "Unknown"),
                to=to_list,
                cc=cc_list,
                bcc=bcc_list,
                unread="UNREAD" in data.get("labelIds", []),
                snippet=data.get("snippet"),
                body_text=body_text,
                body_html=body_html,
                folders=data.get("labelIds", []),
                has_attachments=bool(attachments),
                attachments=attachments,
                provider=self.provider_id,
            )

            return EmailReadResponse(message=detail, provider=self.provider_id)
            
        except ValueError as e:
            return EmailReadResponse(provider=self.provider_id, error=str(e))
        except Exception as e:
            return EmailReadResponse(provider=self.provider_id, error=f"Read failed: {str(e)}")
