"""
Mock email provider for the Unified Email Tool Base.

Useful for testing workflows that send/read emails without hitting real APIs.
Maintains an in-memory database of emails for a given session.
"""

from datetime import datetime, timezone
import uuid

from aden_tools.tools.email_tool.base import BaseEmailProvider
from aden_tools.tools.email_tool.schemas import (
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


class MockEmailProvider(BaseEmailProvider):
    """
    An in-memory email provider for testing and validation.
    
    Supports basic reading, sending, searching, and listing via an internal
    list of stored EmailMessageDetail objects.
    """

    def __init__(self):
        super().__init__()
        self._store: list[EmailMessageDetail] = []
        
        # Pre-seed with some messages if empty
        self._seed_data()

    def _seed_data(self):
        """Seed a few mock messages so tests have something to find initially."""
        m1 = EmailMessageDetail(
            message_id="mock-id-1",
            thread_id="mock-thread-1",
            subject="Welcome to Hive",
            sender="admin@hive.local",
            to=["user@hive.local"],
            cc=[],
            bcc=[],
            sent_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
            unread=True,
            snippet="Welcome aboard! Here are your next steps...",
            body_text="Welcome aboard! Here are your next steps...",
            body_html="<h1>Welcome aboard!</h1><p>Here are your next steps...</p>",
            folders=["inbox"],
            has_attachments=False,
            attachments=[],
            provider=self.provider_id
        )
        self._store.append(m1)

    @property
    def provider_id(self) -> str:
        return "mock"

    def send_email(self, req: EmailSendRequest) -> EmailSendResponse:
        """Stores the sent email in memory."""
        
        message_id = f"sent-mock-{uuid.uuid4().hex[:8]}"
        thread_id = req.reply_to_message_id or f"thread-mock-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        
        snippet = req.body_text[:100] if req.body_text else "HTML Message"
        
        new_msg = EmailMessageDetail(
            message_id=message_id,
            thread_id=thread_id,
            subject=req.subject,
            sender=req.from_email or "system@mock.local",
            to=req.to,
            cc=req.cc or [],
            bcc=req.bcc or [],
            sent_at=now,
            received_at=now,
            unread=False,
            snippet=snippet,
            body_text=req.body_text,
            body_html=req.body_html,
            folders=["sent"],
            has_attachments=False,
            attachments=[],
            provider=self.provider_id
        )
        self._store.append(new_msg)

        return EmailSendResponse(
            success=True,
            message_id=message_id,
            thread_id=thread_id,
            provider=self.provider_id,
            error=None
        )

    def list_emails(self, req: EmailListRequest) -> EmailListResponse:
        """Lists emails from memory, sorted newest first."""
        
        results = [m for m in self._store]
        
        if req.folder:
            results = [m for m in results if req.folder.lower() in [f.lower() for f in m.folders]]
            
        if req.unread_only:
            results = [m for m in results if m.unread]
            
        # Sort newest first
        results.sort(key=lambda x: x.received_at, reverse=True)
        
        # Apply limit
        results = results[:req.limit]
        
        summaries = [EmailMessageSummary(**m.model_dump()) for m in results]
        
        return EmailListResponse(
            messages=summaries,
            provider=self.provider_id,
            error=None
        )

    def search_emails(self, req: EmailSearchRequest) -> EmailSearchResponse:
        """Searches emails in memory."""
        
        results = [m for m in self._store]
        
        if req.query:
            q = req.query.lower()
            results = [
                m for m in results 
                if q in m.subject.lower() or 
                   (m.body_text and q in m.body_text.lower())
            ]
            
        if req.sender:
            results = [m for m in results if req.sender.lower() in m.sender.lower()]
            
        if req.subject_contains:
            results = [m for m in results if req.subject_contains.lower() in m.subject.lower()]
            
        if req.unread_only is True:
            results = [m for m in results if m.unread]
        elif req.unread_only is False:
            results = [m for m in results if not m.unread]
            
        if req.folder:
            results = [m for m in results if req.folder.lower() in [f.lower() for f in m.folders]]
            
        # Basic date filtering
        if req.date_from:
            results = [m for m in results if m.received_at and m.received_at >= req.date_from]
        if req.date_to:
            results = [m for m in results if m.received_at and m.received_at <= req.date_to]
            
        results.sort(key=lambda x: x.received_at, reverse=True)
        results = results[:req.limit]
        
        summaries = [EmailMessageSummary(**m.model_dump()) for m in results]
        
        return EmailSearchResponse(
            messages=summaries,
            provider=self.provider_id,
            error=None
        )

    def read_email(self, req: EmailReadRequest) -> EmailReadResponse:
        """Reads a specific email from memory."""
        
        for msg in self._store:
            if msg.message_id == req.message_id:
                # Shallow copy to modify for response
                ret = msg.model_copy()
                
                # Strip HTML body if not requested
                if not req.include_body_html:
                    ret.body_html = None
                    
                # Strip attachments if not requested
                if not req.include_attachments_metadata:
                    ret.attachments = []
                    
                return EmailReadResponse(
                    message=ret,
                    provider=self.provider_id,
                    error=None
                )
                
        return EmailReadResponse(
            message=None,
            provider=self.provider_id,
            error=f"Message {req.message_id} not found."
        )

    def list_folders(self) -> list[EmailFolder]:
        return [
            EmailFolder(id="inbox", name="Inbox", type="inbox"),
            EmailFolder(id="sent", name="Sent Mails", type="sent"),
            EmailFolder(id="drafts", name="Drafts", type="drafts"),
            EmailFolder(id="trash", name="Trash", type="trash"),
        ]
