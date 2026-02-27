"""
Aden Sync Provider.

Provider that synchronizes credentials with the Aden authentication server.
The Aden server is the authoritative source for OAuth2 tokens - this provider
fetches and caches tokens locally while delegating refresh operations to Aden.

Usage:
    from core.framework.credentials import CredentialStore
    from core.framework.credentials.storage import EncryptedFileStorage
    from core.framework.credentials.aden import (
        AdenCredentialClient,
        AdenClientConfig,
        AdenSyncProvider,
    )

    # Configure client (API key loaded from ADEN_API_KEY env var)
    client = AdenCredentialClient(AdenClientConfig(
        base_url=os.environ["ADEN_API_URL"],
    ))

    # Create provider
    provider = AdenSyncProvider(client=client)

    # Create store
    store = CredentialStore(
        storage=EncryptedFileStorage(),
        providers=[provider],
        auto_refresh=True,
    )

    # Initial sync from Aden
    provider.sync_all(store)

    # Use normally - auto-refreshes via Aden when needed
    token = store.get_key("hubspot", "access_token")
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import SecretStr

from ..models import CredentialKey, CredentialObject, CredentialRefreshError, CredentialType
from ..provider import CredentialProvider
from .client import (
    AdenClientError,
    AdenCredentialClient,
    AdenCredentialResponse,
    AdenRefreshError,
)

if TYPE_CHECKING:
    from ..store import CredentialStore

logger = logging.getLogger(__name__)


class AdenSyncProvider(CredentialProvider):
    """
    Provider that synchronizes credentials with the Aden server.

    The Aden server handles OAuth2 authorization flows and maintains
    refresh tokens. This provider:

    - Fetches access tokens from the Aden server
    - Delegates token refresh to the Aden server
    - Caches tokens locally in the credential store
    - Optionally reports usage statistics back to Aden

    Key benefits:
    - Client secrets never leave the Aden server
    - Refresh token security (stored only on Aden)
    - Centralized audit logging
    - Multi-tenant support

    Usage:
        client = AdenCredentialClient(AdenClientConfig(
            base_url="https://api.adenhq.com",
            api_key=os.environ["ADEN_API_KEY"],
        ))

        provider = AdenSyncProvider(client=client)

        store = CredentialStore(
            storage=EncryptedFileStorage(),
            providers=[provider],
            auto_refresh=True,
        )
    """

    def __init__(
        self,
        client: AdenCredentialClient,
        provider_id: str = "aden_sync",
        refresh_buffer_minutes: int = 5,
        report_usage: bool = False,
    ):
        """
        Initialize the Aden sync provider.

        Args:
            client: Configured Aden API client.
            provider_id: Unique identifier for this provider instance.
                        Useful for multi-tenant scenarios (e.g., 'aden_tenant_123').
            refresh_buffer_minutes: Minutes before expiry to trigger refresh.
                                   Default is 5 minutes.
            report_usage: Whether to report usage statistics to Aden server.
        """
        self._client = client
        self._provider_id = provider_id
        self._refresh_buffer = timedelta(minutes=refresh_buffer_minutes)
        self._report_usage = report_usage

    @property
    def provider_id(self) -> str:
        """Unique identifier for this provider."""
        return self._provider_id

    @property
    def supported_types(self) -> list[CredentialType]:
        """Credential types this provider can manage."""
        return [CredentialType.OAUTH2, CredentialType.BEARER_TOKEN]

    def can_handle(self, credential: CredentialObject) -> bool:
        """
        Check if this provider can handle a credential.

        Returns True if:
        - Credential type is supported (OAUTH2 or BEARER_TOKEN)
        - Credential's provider_id matches this provider, OR
        - Credential has '_aden_managed' metadata flag
        """
        if credential.credential_type not in self.supported_types:
            return False

        # Check if credential is explicitly linked to this provider
        if credential.provider_id == self.provider_id:
            return True

        # Check for Aden-managed flag in metadata
        aden_flag = credential.keys.get("_aden_managed")
        if aden_flag and aden_flag.value.get_secret_value() == "true":
            return True

        return False

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Refresh credential by requesting new token from Aden server.

        The Aden server handles the actual OAuth2 refresh token flow.
        This method simply fetches the result.

        Args:
            credential: The credential to refresh.

        Returns:
            Updated credential with new access token.

        Raises:
            CredentialRefreshError: If refresh fails.
        """
        try:
            # Request Aden to refresh the token
            aden_response = self._client.request_refresh(credential.id)

            # Update credential with new values
            credential = self._update_credential_from_aden(credential, aden_response)

            logger.info(f"Refreshed credential '{credential.id}' via Aden server")

            # Report usage if enabled
            if self._report_usage:
                self._client.report_usage(
                    integration_id=credential.id,
                    operation="token_refresh",
                    status="success",
                )

            return credential

        except AdenRefreshError as e:
            logger.error(f"Aden refresh failed for '{credential.id}': {e}")

            if e.requires_reauthorization:
                raise CredentialRefreshError(
                    f"Integration '{credential.id}' requires re-authorization. "
                    f"Visit: {e.reauthorization_url or 'your Aden dashboard'}"
                ) from e

            raise CredentialRefreshError(
                f"Failed to refresh credential '{credential.id}': {e}"
            ) from e

        except AdenClientError as e:
            logger.error(f"Aden client error for '{credential.id}': {e}")

            # Check if local token is still valid
            access_key = credential.keys.get("access_token")
            if access_key and access_key.expires_at:
                if datetime.now(UTC) < access_key.expires_at:
                    logger.warning(f"Aden unavailable, using cached token for '{credential.id}'")
                    return credential

            raise CredentialRefreshError(
                f"Aden server unavailable and token expired for '{credential.id}'"
            ) from e

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate credential via Aden server introspection.

        Args:
            credential: The credential to validate.

        Returns:
            True if credential is valid.
        """
        try:
            result = self._client.validate_token(credential.id)
            return result.get("valid", False)
        except AdenClientError:
            # Fall back to local validation
            access_key = credential.keys.get("access_token")
            if access_key is None:
                return False

            if access_key.expires_at is None:
                # No expiration - assume valid
                return True

            return datetime.now(UTC) < access_key.expires_at

    def should_refresh(self, credential: CredentialObject) -> bool:
        """
        Check if credential should be refreshed.

        Returns True if access_token is expired or within the refresh buffer.

        Args:
            credential: The credential to check.

        Returns:
            True if credential should be refreshed.
        """
        access_key = credential.keys.get("access_token")
        if access_key is None:
            return False

        if access_key.expires_at is None:
            return False

        # Refresh if within buffer of expiration
        return datetime.now(UTC) >= (access_key.expires_at - self._refresh_buffer)

    def fetch_from_aden(self, integration_id: str) -> CredentialObject | None:
        """
        Fetch credential directly from Aden server.

        Use this for initial population or when local cache is missing.

        Args:
            integration_id: The integration identifier (e.g., 'hubspot').

        Returns:
            CredentialObject if found, None otherwise.

        Raises:
            AdenClientError: For connection failures.
        """
        aden_response = self._client.get_credential(integration_id)
        if aden_response is None:
            return None

        return self._aden_response_to_credential(aden_response)

    def sync_all(self, store: CredentialStore) -> int:
        """
        Sync all credentials from Aden server to local store.

        Calls GET /v1/credentials to list integrations, then fetches
        access tokens for each active one.

        Args:
            store: The credential store to populate.

        Returns:
            Number of credentials synced.
        """
        synced = 0

        try:
            integrations = self._client.list_integrations()

            for info in integrations:
                if info.status != "active":
                    logger.warning(f"Skipping connection '{info.alias}': status={info.status}")
                    continue

                try:
                    cred = self.fetch_from_aden(info.integration_id)
                    if cred:
                        store.save_credential(cred)
                        synced += 1
                        logger.info(f"Synced credential '{info.alias}' from Aden")
                except Exception as e:
                    logger.warning(f"Failed to sync '{info.alias}': {e}")

        except AdenClientError as e:
            logger.error(f"Failed to list integrations from Aden: {e}")

        return synced

    def report_credential_usage(
        self,
        credential: CredentialObject,
        operation: str,
        status: str = "success",
        metadata: dict | None = None,
    ) -> None:
        """
        Report credential usage to Aden server.

        Args:
            credential: The credential that was used.
            operation: Operation name (e.g., 'api_call').
            status: Operation status ('success', 'error').
            metadata: Additional metadata.
        """
        if self._report_usage:
            self._client.report_usage(
                integration_id=credential.id,
                operation=operation,
                status=status,
                metadata=metadata or {},
            )

    def _update_credential_from_aden(
        self,
        credential: CredentialObject,
        aden_response: AdenCredentialResponse,
    ) -> CredentialObject:
        """Update credential object from Aden response."""
        # Update access token
        credential.keys["access_token"] = CredentialKey(
            name="access_token",
            value=SecretStr(aden_response.access_token),
            expires_at=aden_response.expires_at,
        )

        # Update scopes if present
        if aden_response.scopes:
            credential.keys["scope"] = CredentialKey(
                name="scope",
                value=SecretStr(" ".join(aden_response.scopes)),
            )

        # Mark as Aden-managed
        credential.keys["_aden_managed"] = CredentialKey(
            name="_aden_managed",
            value=SecretStr("true"),
        )

        # Store integration type
        credential.keys["_integration_type"] = CredentialKey(
            name="_integration_type",
            value=SecretStr(aden_response.integration_type),
        )

        # Store alias (user-set name from Aden platform)
        if aden_response.alias:
            credential.keys["_alias"] = CredentialKey(
                name="_alias",
                value=SecretStr(aden_response.alias),
            )

        # Persist Aden metadata as identity keys
        for meta_key, meta_value in (aden_response.metadata or {}).items():
            if meta_value and isinstance(meta_value, str):
                credential.keys[f"_identity_{meta_key}"] = CredentialKey(
                    name=f"_identity_{meta_key}",
                    value=SecretStr(meta_value),
                )

        # Update timestamps
        credential.last_refreshed = datetime.now(UTC)
        credential.provider_id = self.provider_id

        return credential

    def _aden_response_to_credential(
        self,
        aden_response: AdenCredentialResponse,
    ) -> CredentialObject:
        """Convert Aden response to CredentialObject."""
        keys: dict[str, CredentialKey] = {
            "access_token": CredentialKey(
                name="access_token",
                value=SecretStr(aden_response.access_token),
                expires_at=aden_response.expires_at,
            ),
            "_aden_managed": CredentialKey(
                name="_aden_managed",
                value=SecretStr("true"),
            ),
            "_integration_type": CredentialKey(
                name="_integration_type",
                value=SecretStr(aden_response.integration_type),
            ),
        }

        # Store alias (user-set name from Aden platform)
        if aden_response.alias:
            keys["_alias"] = CredentialKey(
                name="_alias",
                value=SecretStr(aden_response.alias),
            )

        if aden_response.scopes:
            keys["scope"] = CredentialKey(
                name="scope",
                value=SecretStr(" ".join(aden_response.scopes)),
            )

        # Persist Aden metadata as identity keys
        for meta_key, meta_value in (aden_response.metadata or {}).items():
            if meta_value and isinstance(meta_value, str):
                keys[f"_identity_{meta_key}"] = CredentialKey(
                    name=f"_identity_{meta_key}",
                    value=SecretStr(meta_value),
                )

        return CredentialObject(
            id=aden_response.integration_id,
            credential_type=CredentialType.OAUTH2,
            keys=keys,
            provider_id=self.provider_id,
            auto_refresh=True,
        )
