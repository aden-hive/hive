"""
Normalized schemas for the Unified Email Tool Base.

These Pydantic models represent the core domain objects for email operations
regardless of the underlying provider (Gmail, Outlook, etc.).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Domain Entities
# -----------------------------------------------------------------------------

ProviderType = Literal["auto", "gmail", "outlook", "resend", "mock"]


class EmailAddress(BaseModel):
    """Represents a parsed email address, optionally with a display name."""

    email: str = Field(description="The actual email address, e.g., 'user@example.com'.")
    name: str | None = Field(default=None, description="The display name, e.g., 'John Doe'.")


class EmailFolder(BaseModel):
    """Represents a folder or label in the provider's system."""

    id: str = Field(description="The provider-specific ID of the folder/label.")
    name: str = Field(description="The human-readable name of the folder/label.")
    type: Literal["inbox", "sent", "drafts", "trash", "archive", "custom"] = Field(
        default="custom", description="The normalized type of folder."
    )


class AttachmentMetadata(BaseModel):
    """Metadata for an email attachment."""

    id: str = Field(description="Provider-specific ID for the attachment.")
    filename: str = Field(description="Original filename of the attachment.")
    content_type: str = Field(description="MIME type of the attachment.")
    size_bytes: int | None = Field(default=None, description="Size of the attachment in bytes.")


class EmailMessageSummary(BaseModel):
    """A lightweight summary of an email message, suitable for list views."""

    message_id: str = Field(description="The provider's unique ID for the message.")
    thread_id: str | None = Field(
        default=None, description="The ID of the thread this message belongs to."
    )
    subject: str = Field(description="The email subject line.")
    sender: str = Field(description="The sender's email address.")
    to: list[str] = Field(description="List of primary recipient email addresses.")
    sent_at: datetime | None = Field(default=None, description="When the email was sent.")
    unread: bool = Field(default=False, description="True if the message is unread.")
    snippet: str | None = Field(
        default=None, description="A short text preview of the message body."
    )
    folders: list[str] = Field(
        default_factory=list, description="IDs or names of folders/labels this message is in."
    )
    has_attachments: bool = Field(default=False, description="True if the message has attachments.")
    provider: str = Field(description="The provider that originated this message (e.g., 'gmail').")


class EmailMessageDetail(EmailMessageSummary):
    """The fully detailed view of an email message, including body content."""

    cc: list[str] = Field(default_factory=list, description="List of CC recipient addresses.")
    bcc: list[str] = Field(default_factory=list, description="List of BCC recipient addresses.")
    received_at: datetime | None = Field(
        default=None, description="When the email was received by the server."
    )
    body_text: str | None = Field(default=None, description="The plain text body of the email.")
    body_html: str | None = Field(default=None, description="The HTML body of the email.")
    attachments: list[AttachmentMetadata] = Field(
        default_factory=list, description="List of attachment metadata."
    )
    raw_metadata: dict | None = Field(
        default=None, description="Provider-specific raw metadata (optional)."
    )


# -----------------------------------------------------------------------------
# Operation Requests & Responses
# -----------------------------------------------------------------------------


class EmailSendRequest(BaseModel):
    """Request to send a new email or reply to an existing one."""

    to: list[str] = Field(description="Primary recipients.")
    subject: str = Field(description="The email subject line.")
    body_text: str | None = Field(default=None, description="Plain text body.")
    body_html: str | None = Field(default=None, description="HTML body.")
    from_email: str | None = Field(default=None, description="Sender address to dispatch from.")
    cc: list[str] | None = Field(default=None, description="CC recipients.")
    bcc: list[str] | None = Field(default=None, description="BCC recipients.")
    reply_to_message_id: str | None = Field(
        default=None, description="If provided, sends as a reply to this message."
    )
    provider: ProviderType = Field(
        default="auto", description="Which provider to use. 'auto' infers from credentials."
    )


class EmailSendResponse(BaseModel):
    """Result of a send operation."""

    success: bool = Field(description="True if the email was sent successfully.")
    message_id: str | None = Field(default=None, description="The ID of the sent message.")
    thread_id: str | None = Field(default=None, description="The ID of the thread.")
    provider: str = Field(description="The provider used to send the message.")
    error: str | None = Field(default=None, description="Error message if send failed.")


class EmailListRequest(BaseModel):
    """Request to list recent emails."""

    folder: str | None = Field(
        default=None, description="Folder or label ID to list from (e.g., 'inbox')."
    )
    limit: int = Field(default=10, description="Maximum number of messages to return.")
    unread_only: bool = Field(default=False, description="If true, only return unread messages.")
    provider: ProviderType = Field(
        default="auto", description="Which provider to use. 'auto' infers from credentials."
    )


class EmailListResponse(BaseModel):
    """Result of a list operation."""

    messages: list[EmailMessageSummary] = Field(description="The listed messages.")
    provider: str = Field(description="The provider that fulfilled the request.")
    error: str | None = Field(default=None, description="Error message if fetch failed.")


class EmailSearchRequest(BaseModel):
    """Request to search for emails."""

    query: str | None = Field(default=None, description="Provider-native search query string.")
    sender: str | None = Field(default=None, description="Filter by sender email or name.")
    subject_contains: str | None = Field(default=None, description="Filter by subject substring.")
    unread_only: bool | None = Field(
        default=None, description="If true, only return unread messages."
    )
    date_from: datetime | None = Field(default=None, description="Search emails after this date.")
    date_to: datetime | None = Field(default=None, description="Search emails before this date.")
    folder: str | None = Field(default=None, description="Restrict search to this folder/label ID.")
    limit: int = Field(default=10, description="Maximum number of messages to return.")
    provider: ProviderType = Field(
        default="auto", description="Which provider to use. 'auto' infers from credentials."
    )


class EmailSearchResponse(BaseModel):
    """Result of a search operation."""

    messages: list[EmailMessageSummary] = Field(description="Messages matching the search.")
    provider: str = Field(description="The provider that fulfilled the request.")
    error: str | None = Field(default=None, description="Error message if search failed.")


class EmailReadRequest(BaseModel):
    """Request to fetch a single, fully detailed email message."""

    message_id: str = Field(description="The ID of the message to read.")
    include_body_html: bool = Field(
        default=True, description="Whether to include the HTML body if available."
    )
    include_attachments_metadata: bool = Field(
        default=True, description="Whether to include metadata about attachments."
    )
    provider: ProviderType = Field(
        default="auto", description="Which provider to use. 'auto' infers from credentials."
    )


class EmailReadResponse(BaseModel):
    """Result of a read operation."""

    message: EmailMessageDetail | None = Field(
        default=None, description="The message details, if found."
    )
    provider: str = Field(description="The provider that fulfilled the request.")
    error: str | None = Field(default=None, description="Error message if fetch failed.")
