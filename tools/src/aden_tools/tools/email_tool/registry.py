"""
Provider registry for the Unified Email Tool Base.

Responsible for discovering configured credentials and returning the 
appropriate BaseEmailProvider implementation.
"""

import os
from typing import TYPE_CHECKING, Literal, Type

from aden_tools.tools.email_tool.base import BaseEmailProvider
from aden_tools.tools.email_tool.providers.mock import MockEmailProvider
from aden_tools.tools.email_tool.schemas import ProviderType

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class ProviderRegistry:
    """
    Manages the available email providers and resolves requests to the correct implementation
    based on the requested provider ID and available credentials.
    """

    def __init__(self, credentials: "CredentialStoreAdapter | None" = None):
        """
        Store the global credentials adapter for checking available connections.
        
        Args:
            credentials: The Hive CredentialStoreAdapter (if available in the context).
        """
        self.credentials = credentials
        
        # We load providers lazily or explicitly here to avoid cyclic imports
        self._providers: dict[str, BaseEmailProvider] = {
            "mock": MockEmailProvider()
        }

    def _has_gmail_credentials(self) -> bool:
        """Check if Gmail credentials exist either in env or the credential store."""
        if self.credentials and self.credentials.get("google"):
            return True
        return bool(os.getenv("GOOGLE_ACCESS_TOKEN"))

    def _has_resend_credentials(self) -> bool:
        """Check if Resend credentials exist in env or credential store."""
        if self.credentials and self.credentials.get("resend"):
            return True
        return bool(os.getenv("RESEND_API_KEY"))

    def _infer_provider(self) -> str:
        """Auto-detect the best provider based on available credentials."""
        # Priority 1: If Google/Gmail is connected, prefer it for reading/searching
        if self._has_gmail_credentials():
            return "gmail"
            
        # Priority 2: If Resend is configured, we can send (but maybe not read)
        if self._has_resend_credentials():
            return "resend"
            
        # Fallback to mock if nothing is configured but we need to run tests
        # or alert the user through a clear tool error instead of crashing.
        return "mock"

    def get_provider(self, provider_id: ProviderType = "auto", account_alias: str = "") -> BaseEmailProvider:
        """
        Get an instantiated provider.
        
        Args:
            provider_id: The requested provider ('auto', 'gmail', 'outlook', 'mock').
            account_alias: An optional alias to pass to providers that support multi-account (like Gmail).
            
        Raises:
            ValueError: If the requested provider is entirely unrecognized or not implemented yet.
        """
        # Resolve 'auto' to a concrete provider identifier string
        actual_provider_id = self._infer_provider() if provider_id == "auto" else provider_id

        # Return mock immediately if requested
        if actual_provider_id == "mock":
            return self._providers["mock"]

        # Lazy load Gmail provider to ensure dependencies like httpx are only evaluated if needed
        if actual_provider_id == "gmail":
            from aden_tools.tools.email_tool.providers.gmail import GmailEmailProvider
            
            # Since credentials can be dynamic, we just pass the Store down so the provider 
            # can fetch the token precisely when needed.
            return GmailEmailProvider(self.credentials, account_alias)

        # Lazy load Resend provider (which might only support send_email)
        if actual_provider_id == "resend":
            from aden_tools.tools.email_tool.providers.resend import ResendEmailProvider
            return ResendEmailProvider(self.credentials)

        # If it's an unsupported string
        raise ValueError(
            f"Email provider '{actual_provider_id}' is not currently configured or supported by this Hive system."
        )
