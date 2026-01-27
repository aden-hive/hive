"""
Provider interface for credential lifecycle management.

Providers handle credential lifecycle operations:
- Refresh: Obtain new tokens when expired
- Validate: Check if credentials are still working
- Revoke: Invalidate credentials when no longer needed

OSS users can implement custom providers by subclassing CredentialProvider.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import List

from .models import CredentialObject, CredentialRefreshError, CredentialType

logger = logging.getLogger(__name__)


class CredentialProvider(ABC):
    """
    Abstract base class for credential providers.

    Providers handle credential lifecycle operations:
    - refresh(): Obtain new tokens when expired
    - validate(): Check if credentials are still working
    - should_refresh(): Determine if a credential needs refresh
    - revoke(): Invalidate credentials (optional)

    Example custom provider:
        class MyCustomProvider(CredentialProvider):
            @property
            def provider_id(self) -> str:
                return "my_custom"

            @property
            def supported_types(self) -> List[CredentialType]:
                return [CredentialType.CUSTOM]

            def refresh(self, credential: CredentialObject) -> CredentialObject:
                # Custom refresh logic
                new_token = my_api.refresh(credential.get_key("api_key"))
                credential.set_key("access_token", new_token)
                return credential

            def validate(self, credential: CredentialObject) -> bool:
                token = credential.get_key("access_token")
                return my_api.validate(token)
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """
        Unique identifier for this provider.

        Examples: 'static', 'oauth2', 'my_custom_auth'
        """
        pass

    @property
    @abstractmethod
    def supported_types(self) -> List[CredentialType]:
        """
        Credential types this provider can manage.

        Returns:
            List of CredentialType enums this provider supports
        """
        pass

    @abstractmethod
    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Refresh the credential (e.g., use refresh_token to get new access_token).

        This method should:
        1. Use existing credential data to obtain new values
        2. Update the credential object with new values
        3. Set appropriate expiration times
        4. Update last_refreshed timestamp

        Args:
            credential: The credential to refresh

        Returns:
            Updated credential with new values

        Raises:
            CredentialRefreshError: If refresh fails
        """
        pass

    @abstractmethod
    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate that a credential is still working.

        This might involve:
        - Checking expiration times
        - Making a test API call
        - Validating token signatures

        Args:
            credential: The credential to validate

        Returns:
            True if credential is valid, False otherwise
        """
        pass

    def should_refresh(self, credential: CredentialObject) -> bool:
        """
        Determine if a credential should be refreshed.

        Default implementation: refresh if any key is expired or within
        5 minutes of expiry. Override for custom logic.

        Args:
            credential: The credential to check

        Returns:
            True if credential should be refreshed
        """
        buffer = timedelta(minutes=5)
        now = datetime.now(timezone.utc)

        for key in credential.keys.values():
            if key.expires_at is not None:
                if key.expires_at <= now + buffer:
                    return True
        return False

    def revoke(self, credential: CredentialObject) -> bool:
        """
        Revoke a credential (optional operation).

        Not all providers support revocation. The default implementation
        logs a warning and returns False.

        Args:
            credential: The credential to revoke

        Returns:
            True if revocation succeeded, False otherwise
        """
        logger.warning(f"Provider '{self.provider_id}' does not support revocation")
        return False

    def can_handle(self, credential: CredentialObject) -> bool:
        """
        Check if this provider can handle a credential.

        Args:
            credential: The credential to check

        Returns:
            True if this provider can manage the credential
        """
        return credential.credential_type in self.supported_types


class StaticProvider(CredentialProvider):
    """
    Provider for static credentials that never need refresh.

    Use for simple API keys that don't expire, such as:
    - Brave Search API key
    - OpenAI API key
    - Basic auth credentials

    Static credentials are always considered valid if they have at least one key.
    """

    @property
    def provider_id(self) -> str:
        return "static"

    @property
    def supported_types(self) -> List[CredentialType]:
        return [CredentialType.API_KEY, CredentialType.BASIC_AUTH, CredentialType.CUSTOM]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Static credentials don't need refresh.

        Returns the credential unchanged.
        """
        logger.debug(f"Static credential '{credential.id}' does not need refresh")
        return credential

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate that credential has at least one key with a value.

        For static credentials, we can't verify the key works without
        making an API call, so we just check existence.
        """
        if not credential.keys:
            return False

        # Check at least one key has a non-empty value
        for key in credential.keys.values():
            try:
                value = key.get_secret_value()
                if value and value.strip():
                    return True
            except Exception:
                continue

        return False

    def should_refresh(self, credential: CredentialObject) -> bool:
        """Static credentials never need refresh."""
        return False


class BearerTokenProvider(CredentialProvider):
    """
    Provider for bearer tokens without refresh capability.

    Use for JWTs or tokens that:
    - Have an expiration time
    - Cannot be refreshed (no refresh token)
    - Must be re-obtained when expired

    This provider validates based on expiration time only.
    """

    @property
    def provider_id(self) -> str:
        return "bearer_token"

    @property
    def supported_types(self) -> List[CredentialType]:
        return [CredentialType.BEARER_TOKEN]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Bearer tokens without refresh capability cannot be refreshed.

        Raises:
            CredentialRefreshError: Always, as refresh is not supported
        """
        raise CredentialRefreshError(
            f"Bearer token '{credential.id}' cannot be refreshed. "
            "Obtain a new token and save it to the credential store."
        )

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate based on expiration time.

        Returns True if token exists and is not expired.
        """
        access_key = credential.keys.get("access_token") or credential.keys.get("token")
        if access_key is None:
            return False

        # Check if expired
        return not access_key.is_expired

    def should_refresh(self, credential: CredentialObject) -> bool:
        """
        Check if token is expired or near expiration.

        Note: Even though this returns True for expired tokens,
        refresh() will fail. This allows the store to know the
        credential needs attention.
        """
        buffer = timedelta(minutes=5)
        now = datetime.now(timezone.utc)

        for key_name in ["access_token", "token"]:
            key = credential.keys.get(key_name)
            if key and key.expires_at:
                if key.expires_at <= now + buffer:
                    return True

        return False
