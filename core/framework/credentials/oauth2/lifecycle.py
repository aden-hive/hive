"""
Token lifecycle management for OAuth2 credentials.

This module provides the TokenLifecycleManager which coordinates
automatic token refresh with the credential store.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Optional

from pydantic import SecretStr

from ..models import CredentialKey, CredentialObject, CredentialRefreshError, CredentialType
from .base_provider import BaseOAuth2Provider
from .provider import OAuth2Token

if TYPE_CHECKING:
    from ..store import CredentialStore

logger = logging.getLogger(__name__)


@dataclass
class TokenRefreshResult:
    """Result of a token refresh operation."""

    success: bool
    token: Optional[OAuth2Token] = None
    error: Optional[str] = None
    needs_reauthorization: bool = False


class TokenLifecycleManager:
    """
    Manages the complete lifecycle of OAuth2 tokens.

    Responsibilities:
    - Coordinate with CredentialStore for persistence
    - Automatically refresh expired tokens
    - Handle refresh failures gracefully
    - Provide callbacks for monitoring

    This class is useful when you need more control over token management
    than the basic auto-refresh in CredentialStore provides.

    Usage:
        manager = TokenLifecycleManager(
            provider=github_provider,
            credential_id="github_oauth",
            store=credential_store,
        )

        # Get valid token (auto-refreshes if needed)
        token = await manager.get_valid_token()

        # Use token
        headers = provider.format_for_request(token)

    Synchronous usage:
        # For synchronous code, use sync_ methods
        token = manager.sync_get_valid_token()
    """

    def __init__(
        self,
        provider: BaseOAuth2Provider,
        credential_id: str,
        store: "CredentialStore",
        refresh_buffer_minutes: int = 5,
        on_token_refreshed: Optional[Callable[[OAuth2Token], None]] = None,
        on_refresh_failed: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the lifecycle manager.

        Args:
            provider: OAuth2 provider for token operations
            credential_id: ID of the credential in the store
            store: Credential store for persistence
            refresh_buffer_minutes: Minutes before expiry to trigger refresh
            on_token_refreshed: Callback when token is refreshed
            on_refresh_failed: Callback when refresh fails
        """
        self.provider = provider
        self.credential_id = credential_id
        self.store = store
        self.refresh_buffer = timedelta(minutes=refresh_buffer_minutes)
        self.on_token_refreshed = on_token_refreshed
        self.on_refresh_failed = on_refresh_failed

        # In-memory cache for performance
        self._cached_token: Optional[OAuth2Token] = None
        self._cache_time: Optional[datetime] = None

    # --- Async Token Access ---

    async def get_valid_token(self) -> Optional[OAuth2Token]:
        """
        Get a valid access token, refreshing if necessary.

        This is the main entry point for async code.

        Returns:
            Valid OAuth2Token or None if unavailable
        """
        # Check cache first
        if self._cached_token and not self._needs_refresh(self._cached_token):
            return self._cached_token

        # Load from store
        credential = self.store.get_credential(self.credential_id, refresh_if_needed=False)
        if credential is None:
            return None

        # Convert to OAuth2Token
        token = self._credential_to_token(credential)
        if token is None:
            return None

        # Refresh if needed
        if self._needs_refresh(token):
            result = await self._async_refresh_token(credential)
            if result.success and result.token:
                token = result.token
            elif result.needs_reauthorization:
                logger.warning(f"Token for {self.credential_id} needs reauthorization")
                return None
            else:
                # Use existing token if still technically valid
                if token.is_expired:
                    return None
                logger.warning(f"Refresh failed for {self.credential_id}, using existing token")

        self._cached_token = token
        self._cache_time = datetime.now(timezone.utc)
        return token

    async def acquire_token_client_credentials(
        self,
        scopes: Optional[list[str]] = None,
    ) -> OAuth2Token:
        """
        Acquire a new token using client credentials flow.

        For service-to-service authentication.

        Args:
            scopes: Scopes to request

        Returns:
            New OAuth2Token
        """
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(None, lambda: self.provider.client_credentials_grant(scopes=scopes))

        self._save_token_to_store(token)
        self._cached_token = token
        return token

    async def revoke(self) -> bool:
        """
        Revoke tokens and clear from store.

        Returns:
            True if revocation succeeded
        """
        credential = self.store.get_credential(self.credential_id, refresh_if_needed=False)
        if credential:
            self.provider.revoke(credential)

        self.store.delete_credential(self.credential_id)
        self._cached_token = None
        return True

    # --- Synchronous Token Access ---

    def sync_get_valid_token(self) -> Optional[OAuth2Token]:
        """
        Synchronous version of get_valid_token().

        For use in synchronous code.
        """
        # Check cache
        if self._cached_token and not self._needs_refresh(self._cached_token):
            return self._cached_token

        # Load from store
        credential = self.store.get_credential(self.credential_id, refresh_if_needed=False)
        if credential is None:
            return None

        token = self._credential_to_token(credential)
        if token is None:
            return None

        # Refresh if needed
        if self._needs_refresh(token):
            result = self._sync_refresh_token(credential)
            if result.success and result.token:
                token = result.token
            elif result.needs_reauthorization:
                logger.warning(f"Token for {self.credential_id} needs reauthorization")
                return None
            else:
                if token.is_expired:
                    return None

        self._cached_token = token
        self._cache_time = datetime.now(timezone.utc)
        return token

    def sync_acquire_token_client_credentials(
        self,
        scopes: Optional[list[str]] = None,
    ) -> OAuth2Token:
        """Synchronous version of acquire_token_client_credentials()."""
        token = self.provider.client_credentials_grant(scopes=scopes)
        self._save_token_to_store(token)
        self._cached_token = token
        return token

    # --- Helper Methods ---

    def _needs_refresh(self, token: OAuth2Token) -> bool:
        """Check if token needs refresh."""
        if token.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= (token.expires_at - self.refresh_buffer)

    def _credential_to_token(self, credential: CredentialObject) -> Optional[OAuth2Token]:
        """Convert credential to OAuth2Token."""
        access_token = credential.get_key("access_token")
        if not access_token:
            return None

        expires_at = None
        access_key = credential.keys.get("access_token")
        if access_key:
            expires_at = access_key.expires_at

        return OAuth2Token(
            access_token=access_token,
            token_type="Bearer",
            expires_at=expires_at,
            refresh_token=credential.get_key("refresh_token"),
            scope=credential.get_key("scope"),
        )

    def _save_token_to_store(self, token: OAuth2Token) -> None:
        """Save token to credential store."""
        credential = CredentialObject(
            id=self.credential_id,
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr(token.access_token),
                    expires_at=token.expires_at,
                ),
            },
            provider_id=self.provider.provider_id,
            auto_refresh=True,
        )

        if token.refresh_token:
            credential.keys["refresh_token"] = CredentialKey(
                name="refresh_token",
                value=SecretStr(token.refresh_token),
            )

        if token.scope:
            credential.keys["scope"] = CredentialKey(
                name="scope",
                value=SecretStr(token.scope),
            )

        self.store.save_credential(credential)

    async def _async_refresh_token(self, credential: CredentialObject) -> TokenRefreshResult:
        """Async wrapper for token refresh."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._sync_refresh_token(credential))

    def _sync_refresh_token(self, credential: CredentialObject) -> TokenRefreshResult:
        """Synchronously refresh token."""
        refresh_token = credential.get_key("refresh_token")
        if not refresh_token:
            return TokenRefreshResult(
                success=False,
                error="No refresh token available",
                needs_reauthorization=True,
            )

        try:
            new_token = self.provider.refresh_access_token(refresh_token)

            # Save to store
            self._save_token_to_store(new_token)

            # Notify callback
            if self.on_token_refreshed:
                self.on_token_refreshed(new_token)

            logger.info(f"Token refreshed for {self.credential_id}")
            return TokenRefreshResult(success=True, token=new_token)

        except Exception as e:
            error_msg = str(e)

            # Check for refresh token revocation
            if "invalid_grant" in error_msg.lower():
                return TokenRefreshResult(
                    success=False,
                    error=error_msg,
                    needs_reauthorization=True,
                )

            if self.on_refresh_failed:
                self.on_refresh_failed(error_msg)

            logger.error(f"Token refresh failed for {self.credential_id}: {e}")
            return TokenRefreshResult(success=False, error=error_msg)

    def invalidate_cache(self) -> None:
        """Clear cached token."""
        self._cached_token = None
        self._cache_time = None

    # --- Convenience Methods ---

    def get_request_headers(self) -> dict[str, str]:
        """
        Get headers for HTTP request with current token.

        Returns empty dict if no valid token.
        """
        token = self.sync_get_valid_token()
        if token is None:
            return {}

        result = self.provider.format_for_request(token)
        return result.get("headers", {})

    def get_request_kwargs(self) -> dict:
        """
        Get kwargs for HTTP request (headers, params, etc.).

        Returns empty dict if no valid token.
        """
        token = self.sync_get_valid_token()
        if token is None:
            return {}

        return self.provider.format_for_request(token)
