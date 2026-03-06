"""
Resend provider for the Unified Email Tool Base.

Implements the BaseEmailProvider interface but currently only 
supports sending emails via the Resend API.
"""

import os
from typing import TYPE_CHECKING, Any

import resend

from aden_tools.tools.email_tool.base import BaseEmailProvider
from aden_tools.tools.email_tool.schemas import (
    EmailListRequest,
    EmailListResponse,
    EmailReadRequest,
    EmailReadResponse,
    EmailSearchRequest,
    EmailSearchResponse,
    EmailSendRequest,
    EmailSendResponse,
)

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class ResendEmailProvider(BaseEmailProvider):
    """
    Resend implementation of the Email Provider interface.
    
    Currently only supports `send_email`. Search, list, and read will 
    return clear 'unsupported' errors.
    """

    def __init__(self, credentials: "CredentialStoreAdapter | None" = None):
        self.credentials = credentials

    @property
    def provider_id(self) -> str:
        return "resend"

    def _get_api_key(self) -> str:
        if self.credentials:
            key = self.credentials.get("resend")
            if key:
                return key
        key = os.getenv("RESEND_API_KEY")
        if key:
            return key
        raise ValueError("Resend API key missing. Set RESEND_API_KEY or configure via Hive credentials.")

    def send_email(self, req: EmailSendRequest) -> EmailSendResponse:
        try:
            api_key = self._get_api_key()
        except ValueError as e:
            return EmailSendResponse(success=False, provider=self.provider_id, error=str(e))

        resend.api_key = api_key

        payload: dict[str, Any] = {
            "from": req.from_email or os.getenv("EMAIL_FROM") or "onboarding@resend.dev",
            "to": req.to,
            "subject": req.subject,
        }

        if req.body_html:
            payload["html"] = req.body_html
        elif req.body_text:
            payload["text"] = req.body_text
            
        if req.cc:
            payload["cc"] = req.cc
        if req.bcc:
            payload["bcc"] = req.bcc
            
        # Optional: Support threading if resend headers param is mapped
        if req.reply_to_message_id:
            payload["headers"] = {
                "In-Reply-To": req.reply_to_message_id,
                "References": req.reply_to_message_id
            }

        try:
            email = resend.Emails.send(payload)
            return EmailSendResponse(
                success=True,
                message_id=email.get("id"),
                provider=self.provider_id
            )
        except resend.exceptions.ResendError as e:
            return EmailSendResponse(
                success=False,
                provider=self.provider_id, 
                error=f"Resend API error: {e}"
            )
        except Exception as e:
            return EmailSendResponse(
                success=False,
                provider=self.provider_id, 
                error=f"Request failed: {str(e)}"
            )

    def list_emails(self, req: EmailListRequest) -> EmailListResponse:
        return EmailListResponse(
            messages=[], 
            provider=self.provider_id, 
            error="Resend does not currently support listing emails via this interface."
        )

    def search_emails(self, req: EmailSearchRequest) -> EmailSearchResponse:
        return EmailSearchResponse(
            messages=[], 
            provider=self.provider_id, 
            error="Resend does not currently support searching emails via this interface."
        )

    def read_email(self, req: EmailReadRequest) -> EmailReadResponse:
        return EmailReadResponse(
            provider=self.provider_id, 
            error="Resend does not currently support reading emails via this interface."
        )
