"""
Base provider interface for the Unified Email Tool Base.
"""

from abc import ABC, abstractmethod

from aden_tools.tools.email_tool.schemas import (
    EmailFolder,
    EmailListRequest,
    EmailListResponse,
    EmailReadRequest,
    EmailReadResponse,
    EmailSearchRequest,
    EmailSearchResponse,
    EmailSendRequest,
    EmailSendResponse,
)


class BaseEmailProvider(ABC):
    """
    Abstract base class defining the contract for an Email Provider.
    
    Any integrated email provider (e.g., Gmail, Outlook, Mock) must implement
    these core atomic operations. The tool layer calls these methods, ensuring
    agent workflows remain provider-agnostic.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """The identifier string for this provider (e.g., 'gmail', 'outlook')."""
        pass

    @abstractmethod
    def send_email(self, req: EmailSendRequest) -> EmailSendResponse:
        """
        Send a new email or reply to an existing one.
        
        Args:
            req: Normalized send request containing recipients, body, subject, etc.
            
        Returns:
            A normalized response indicating success and returning the new message ID.
        """
        pass

    @abstractmethod
    def list_emails(self, req: EmailListRequest) -> EmailListResponse:
        """
        List recent emails, optionally filtered by folder or read status.
        
        Args:
            req: Normalized list request.
            
        Returns:
            A response containing lightweight summaries of the matched messages.
        """
        pass

    @abstractmethod
    def search_emails(self, req: EmailSearchRequest) -> EmailSearchResponse:
        """
        Search for emails matching the specified criteria.
        
        The provider is responsible for translating the normalized criteria
        (sender, date bounds, etc.) into the provider's native query syntax.
        
        Args:
            req: Normalized search request.
            
        Returns:
            A response containing lightweight summaries of the matched messages.
        """
        pass

    @abstractmethod
    def read_email(self, req: EmailReadRequest) -> EmailReadResponse:
        """
        Fetch the full details of a specific email message.
        
        Args:
            req: Normalized read request containing the message ID.
            
        Returns:
            A response containing the full message details (body text, attachments, etc.).
        """
        pass

    def list_folders(self) -> list[EmailFolder]:
        """
        List available folders or labels.
        
        Providers that do not support this or haven't implemented it can return 
        an empty list, or raise NotImplementedError.
        
        Returns:
            A list of normalized folder objects.
        """
        return []
