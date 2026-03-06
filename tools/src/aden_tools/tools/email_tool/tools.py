"""
Tool interface for the Unified Email Tool Base.

Registers the provider-agnostic email tools with the MCP FastMCP server.
"""

from typing import TYPE_CHECKING
from decimal import Decimal
from datetime import datetime

from fastmcp import FastMCP

from aden_tools.tools.email_tool.schemas import (
    EmailSendRequest,
    EmailListRequest,
    EmailSearchRequest,
    EmailReadRequest,
    ProviderType
)
from aden_tools.tools.email_tool.registry import ProviderRegistry

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: "CredentialStoreAdapter | None" = None,
) -> None:
    """Register the unified email tools with the MCP server."""
    
    registry = ProviderRegistry(credentials)

    @mcp.tool()
    def email_send(
        to: list[str],
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        provider: ProviderType = "auto",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_message_id: str | None = None,
        account_alias: str = ""
    ) -> dict:
        """
        Send a new email or reply to an existing one.
        
        Args:
            to: List of primary recipient email addresses.
            subject: The email subject line.
            body_text: Plain text body of the email.
            body_html: HTML body of the email.
            provider: Which email provider to use ('auto' infers from credentials, or 'gmail', 'mock').
            cc: Optional list of CC recipient addresses.
            bcc: Optional list of BCC recipient addresses.
            reply_to_message_id: If provided, sends this email as a reply within the specified message's thread.
            account_alias: Optional account alias if multiple accounts of the same provider exist.
            
        Returns:
            A dictionary containing success status, message_id, thread_id, and provider used, or an error.
        """
        if not body_text and not body_html:
            return {"error": "Either body_text or body_html must be provided."}
            
        try:
            req = EmailSendRequest(
                to=to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                provider=provider,
                cc=cc,
                bcc=bcc,
                reply_to_message_id=reply_to_message_id
            )
            
            p = registry.get_provider(req.provider, account_alias)
            resp = p.send_email(req)
            return resp.model_dump()
            
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def email_list(
        folder: str | None = None,
        limit: int = 10,
        unread_only: bool = False,
        provider: ProviderType = "auto",
        account_alias: str = ""
    ) -> dict:
        """
        List recent emails from a mailbox.
        
        Args:
            folder: The specific folder or label to list (e.g., 'inbox', 'sent').
            limit: Maximum number of emails to return (default 10).
            unread_only: If true, only returns unread messages.
            provider: Which email provider to use.
            account_alias: Optional account alias if multiple accounts exist.
            
        Returns:
            A list of lightweight email summaries.
        """
        try:
            req = EmailListRequest(
                folder=folder,
                limit=limit,
                unread_only=unread_only,
                provider=provider,
            )
            
            p = registry.get_provider(req.provider, account_alias)
            resp = p.list_emails(req)
            
            # Pydantic dates serialize to native Python dict format, need ISO format for MCP json
            res_dict = resp.model_dump()
            return res_dict
            
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def email_search(
        query: str | None = None,
        sender: str | None = None,
        subject_contains: str | None = None,
        unread_only: bool | None = None,
        limit: int = 10,
        provider: ProviderType = "auto",
        account_alias: str = ""
    ) -> dict:
        """
        Search for emails matching specific criteria.
        
        Args:
            query: Free-text search query (provider-specific native syntax).
            sender: Filter by sender email.
            subject_contains: Filter by subject text.
            unread_only: Filter by read status.
            limit: Maximum number of emails to return (default 10).
            provider: Which email provider to use.
            account_alias: Optional account alias if multiple accounts exist.
            
        Returns:
            A list of lightweight email summaries matching the search.
        """
        try:
            req = EmailSearchRequest(
                query=query,
                sender=sender,
                subject_contains=subject_contains,
                unread_only=unread_only,
                limit=limit,
                provider=provider,
            )
            
            p = registry.get_provider(req.provider, account_alias)
            resp = p.search_emails(req)
            return resp.model_dump()
            
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def email_read(
        message_id: str,
        include_body_html: bool = True,
        include_attachments_metadata: bool = True,
        provider: ProviderType = "auto",
        account_alias: str = ""
    ) -> dict:
        """
        Read the full content and details of a specific email message.
        
        Args:
            message_id: The unique ID of the message to read.
            include_body_html: Whether to fetch and return the HTML body if available.
            include_attachments_metadata: Whether to return information about attachments.
            provider: Which email provider to use.
            account_alias: Optional account alias if multiple accounts exist.
            
        Returns:
            Detailed email payload including bodies and full metadata.
        """
        try:
            req = EmailReadRequest(
                message_id=message_id,
                include_body_html=include_body_html,
                include_attachments_metadata=include_attachments_metadata,
                provider=provider
            )
            
            p = registry.get_provider(req.provider, account_alias)
            resp = p.read_email(req)
            return resp.model_dump()
            
        except Exception as e:
            return {"error": str(e)}
