"""
Main credential store orchestrating storage, providers, and template resolution.

The CredentialStore is the primary interface for credential management, providing:
- Multi-backend storage (file, env, vault)
- Provider-based lifecycle management (refresh, validate)
- Template resolution for {{cred.key}} patterns
- Caching with TTL for performance
- Thread-safe operations
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from .models import (
    CredentialKey,
    CredentialObject,
    CredentialRefreshError,
    CredentialUsageSpec,
)
from .provider import CredentialProvider, StaticProvider
from .storage import CredentialStorage, EnvVarStorage, InMemoryStorage
from .template import TemplateResolver

logger = logging.getLogger(__name__)


class CredentialStore:
    """
    Main credential store orchestrating storage, providers, and template resolution.

    Features:
    - Multi-backend storage (file, env, vault)
    - Provider-based lifecycle management (refresh, validate)
    - Template resolution for {{cred.key}} patterns
    - Caching with TTL for performance
    - Thread-safe operations

    Usage:
        # Basic usage
        store = CredentialStore(
            storage=EncryptedFileStorage("/path/to/creds"),
            providers=[OAuth2Provider(), StaticProvider()]
        )

        # Get a credential
        cred = store.get_credential("github_oauth")

        # Resolve templates in headers
        headers = store.resolve_headers({
            "Authorization": "Bearer {{github_oauth.access_token}}"
        })

        # Register a tool's credential requirements
        store.register_usage(CredentialUsageSpec(
            credential_id="brave_search",
            required_keys=["api_key"],
            headers={"X-Subscription-Token": "{{brave_search.api_key}}"}
        ))
    """

    def __init__(
        self,
        storage: CredentialStorage | None = None,
        providers: list[CredentialProvider] | None = None,
        cache_ttl_seconds: int = 300,
        auto_refresh: bool = True,
    ):
        """
        Initialize the credential store.

        Args:
            storage: Storage backend. Defaults to EnvVarStorage for compatibility.
            providers: List of credential providers. Defaults to [StaticProvider()].
            cache_ttl_seconds: How long to cache credentials in memory (default: 5 minutes).
            auto_refresh: Whether to auto-refresh expired credentials on access.
        """
        self._storage = storage or EnvVarStorage()
        self._providers: dict[str, CredentialProvider] = {}
        self._usage_specs: dict[str, CredentialUsageSpec] = {}

        # Cache: credential_id -> (CredentialObject, cached_at)
        self._cache: dict[str, tuple[CredentialObject, datetime]] = {}
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.RLock()

        self._auto_refresh = auto_refresh

        # Register providers
        for provider in providers or [StaticProvider()]:
            self.register_provider(provider)

        # Template resolver
        self._resolver = TemplateResolver(self)

    # --- Provider Management ---

    def register_provider(self, provider: CredentialProvider) -> None:
        """
        Register a credential provider.

        Args:
            provider: The provider to register
        """
        self._providers[provider.provider_id] = provider
        logger.debug(f"Registered credential provider: {provider.provider_id}")

    def get_provider(self, provider_id: str) -> CredentialProvider | None:
        """
        Get a provider by ID.

        Args:
            provider_id: The provider identifier

        Returns:
            The provider if found, None otherwise
        """
        return self._providers.get(provider_id)

    def get_provider_for_credential(
        self, credential: CredentialObject
    ) -> CredentialProvider | None:
        """
        Get the appropriate provider for a credential.

        Args:
            credential: The credential to find a provider for

        Returns:
            The provider if found, None otherwise
        """
        # First, check if credential specifies a provider
        if credential.provider_id:
            provider = self._providers.get(credential.provider_id)
            if provider:
                return provider

        # Fall back to finding a provider that supports this type
        for provider in self._providers.values():
            if provider.can_handle(credential):
                return provider

        return None

    # --- Usage Spec Management ---

    def register_usage(self, spec: CredentialUsageSpec) -> None:
        """
        Register how a tool uses credentials.

        Args:
            spec: The usage specification
        """
        self._usage_specs[spec.credential_id] = spec

    def get_usage_spec(self, credential_id: str) -> CredentialUsageSpec | None:
        """
        Get the usage spec for a credential.

        Args:
            credential_id: The credential identifier

        Returns:
            The usage spec if registered, None otherwise
        """
        return self._usage_specs.get(credential_id)

    # --- Credential Access ---

    def get_credential(
        self,
        credential_id: str,
        refresh_if_needed: bool = True,
    ) -> CredentialObject | None:
        """
        Get a credential by ID.

        Args:
            credential_id: The credential identifier
            refresh_if_needed: If True, refresh expired credentials

        Returns:
            CredentialObject or None if not found
        """
        with self._lock:
            # Check cache
            cached = self._get_from_cache(credential_id)
            if cached is not None:
                if refresh_if_needed and self._should_refresh(cached):
                    return self._refresh_credential(cached)
                return cached

            # Load from storage
            credential = self._storage.load(credential_id)
            if credential is None:
                return None

            # Refresh if needed
            if refresh_if_needed and self._should_refresh(credential):
                credential = self._refresh_credential(credential)

            # Cache
            self._add_to_cache(credential)

            return credential

    def get_key(self, credential_id: str, key_name: str) -> str | None:
        """
        Convenience method to get a specific key value.

        Args:
            credential_id: The credential identifier
            key_name: The key within the credential

        Returns:
            The key value or None if not found
        """
        credential = self.get_credential(credential_id)
        if credential is None:
            return None
        return credential.get_key(key_name)

    def get(self, credential_id: str) -> str | None:
        """
        Legacy compatibility: get the primary key value.

        For single-key credentials, returns that key.
        For multi-key, returns 'value', 'api_key', or 'access_token'.

        Args:
            credential_id: The credential identifier

        Returns:
            The primary key value or None
        """
        credential = self.get_credential(credential_id)
        if credential is None:
            return None
        return credential.get_default_key()

    # --- Template Resolution ---

    def resolve(self, template: str) -> str:
        """
        Resolve credential templates in a string.

        Args:
            template: String containing {{cred.key}} patterns

        Returns:
            Template with all references resolved

        Example:
            >>> store.resolve("Bearer {{github.access_token}}")
            "Bearer ghp_xxxxxxxxxxxx"
        """
        return self._resolver.resolve(template)

    def resolve_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """
        Resolve credential templates in headers dictionary.

        Args:
            headers: Dict of header name to template value

        Returns:
            Dict with all templates resolved

        Example:
            >>> store.resolve_headers({
            ...     "Authorization": "Bearer {{github.access_token}}"
            ... })
            {"Authorization": "Bearer ghp_xxx"}
        """
        return self._resolver.resolve_headers(headers)

    def resolve_params(self, params: dict[str, str]) -> dict[str, str]:
        """
        Resolve credential templates in query parameters dictionary.

        Args:
            params: Dict of param name to template value

        Returns:
            Dict with all templates resolved
        """
        return self._resolver.resolve_params(params)

    def resolve_for_usage(self, credential_id: str) -> dict[str, Any]:
        """
        Get resolved request kwargs for a registered usage spec.

        Args:
            credential_id: The credential identifier

        Returns:
            Dict with 'headers', 'params', etc. keys as appropriate

        Raises:
            ValueError: If no usage spec is registered for the credential
        """
        spec = self._usage_specs.get(credential_id)
        if spec is None:
            raise ValueError(f"No usage spec registered for '{credential_id}'")

        result: dict[str, Any] = {}

        if spec.headers:
            result["headers"] = self.resolve_headers(spec.headers)

        if spec.query_params:
            result["params"] = self.resolve_params(spec.query_params)

        if spec.body_fields:
            result["data"] = {key: self.resolve(value) for key, value in spec.body_fields.items()}

        return result

    # --- Credential Management ---

    def save_credential(self, credential: CredentialObject) -> None:
        """
        Save a credential to storage.

        Args:
            credential: The credential to save
        """
        with self._lock:
            self._storage.save(credential)
            self._add_to_cache(credential)
            logger.info(f"Saved credential '{credential.id}'")

    def delete_credential(self, credential_id: str) -> bool:
        """
        Delete a credential from storage.

        Args:
            credential_id: The credential identifier

        Returns:
            True if the credential existed and was deleted
        """
        with self._lock:
            self._remove_from_cache(credential_id)
            result = self._storage.delete(credential_id)
            if result:
                logger.info(f"Deleted credential '{credential_id}'")
            return result

    def list_credentials(self) -> list[str]:
        """
        List all available credential IDs.

        Returns:
            List of credential IDs
        """
        return self._storage.list_all()

    def is_available(self, credential_id: str) -> bool:
        """
        Check if a credential is available.

        Args:
            credential_id: The credential identifier

        Returns:
            True if credential exists and is accessible
        """
        return self.get_credential(credential_id, refresh_if_needed=False) is not None

    # --- Validation ---

    def validate_for_usage(self, credential_id: str) -> list[str]:
        """
        Validate that a credential meets its usage spec requirements.

        Args:
            credential_id: The credential identifier

        Returns:
            List of missing keys or errors. Empty list if valid.
        """
        spec = self._usage_specs.get(credential_id)
        if spec is None:
            return []  # No requirements registered

        credential = self.get_credential(credential_id)
        if credential is None:
            return [f"Credential '{credential_id}' not found"]

        errors = []
        for key_name in spec.required_keys:
            if not credential.has_key(key_name):
                errors.append(f"Missing required key '{key_name}'")

        return errors

    def validate_all(self) -> dict[str, list[str]]:
        """
        Validate all registered usage specs.

        Returns:
            Dict mapping credential_id to list of errors.
            Only includes credentials with errors.
        """
        errors = {}
        for cred_id in self._usage_specs.keys():
            cred_errors = self.validate_for_usage(cred_id)
            if cred_errors:
                errors[cred_id] = cred_errors
        return errors

    def validate_credential(self, credential_id: str) -> bool:
        """
        Validate a credential using its provider.

        Args:
            credential_id: The credential identifier

        Returns:
            True if credential is valid
        """
        credential = self.get_credential(credential_id, refresh_if_needed=False)
        if credential is None:
            return False

        provider = self.get_provider_for_credential(credential)
        if provider is None:
            # No provider, assume valid if has keys
            return bool(credential.keys)

        return provider.validate(credential)

    # --- Lifecycle Management ---

    def _should_refresh(self, credential: CredentialObject) -> bool:
        """Check if credential should be refreshed."""
        if not self._auto_refresh:
            return False

        if not credential.auto_refresh:
            return False

        provider = self.get_provider_for_credential(credential)
        if provider is None:
            return False

        return provider.should_refresh(credential)

    def _refresh_credential(self, credential: CredentialObject) -> CredentialObject:
        """Refresh a credential using its provider."""
        provider = self.get_provider_for_credential(credential)
        if provider is None:
            logger.warning(f"No provider found for credential '{credential.id}'")
            return credential

        try:
            refreshed = provider.refresh(credential)
            refreshed.last_refreshed = datetime.now(UTC)

            # Persist the refreshed credential
            self._storage.save(refreshed)
            self._add_to_cache(refreshed)

            logger.info(f"Refreshed credential '{credential.id}'")
            return refreshed

        except CredentialRefreshError as e:
            logger.error(f"Failed to refresh credential '{credential.id}': {e}")
            return credential

    def refresh_credential(self, credential_id: str) -> CredentialObject | None:
        """
        Manually refresh a credential.

        Args:
            credential_id: The credential identifier

        Returns:
            The refreshed credential, or None if not found

        Raises:
            CredentialRefreshError: If refresh fails
        """
        credential = self.get_credential(credential_id, refresh_if_needed=False)
        if credential is None:
            return None

        return self._refresh_credential(credential)

    # --- Caching ---

    def _get_from_cache(self, credential_id: str) -> CredentialObject | None:
        """Get credential from cache if not expired."""
        if credential_id not in self._cache:
            return None

        credential, cached_at = self._cache[credential_id]
        age = (datetime.now(UTC) - cached_at).total_seconds()

        if age > self._cache_ttl:
            del self._cache[credential_id]
            return None

        return credential

    def _add_to_cache(self, credential: CredentialObject) -> None:
        """Add credential to cache."""
        self._cache[credential.id] = (credential, datetime.now(UTC))

    def _remove_from_cache(self, credential_id: str) -> None:
        """Remove credential from cache."""
        self._cache.pop(credential_id, None)

    def clear_cache(self) -> None:
        """Clear the credential cache."""
        with self._lock:
            self._cache.clear()

    # --- Factory Methods ---

    @classmethod
    def for_testing(
        cls,
        credentials: dict[str, dict[str, str]],
    ) -> CredentialStore:
        """
        Create a credential store for testing with mock credentials.

        Args:
            credentials: Dict mapping credential_id to {key_name: value}
                        e.g., {"brave_search": {"api_key": "test-key"}}

        Returns:
            CredentialStore with in-memory credentials

        Example:
            store = CredentialStore.for_testing({
                "brave_search": {"api_key": "test-brave-key"},
                "github_oauth": {
                    "access_token": "test-token",
                    "refresh_token": "test-refresh"
                }
            })
        """
        # Convert test data to CredentialObjects
        cred_objects: dict[str, CredentialObject] = {}

        for cred_id, keys in credentials.items():
            cred_objects[cred_id] = CredentialObject(
                id=cred_id,
                keys={k: CredentialKey(name=k, value=SecretStr(v)) for k, v in keys.items()},
            )

        return cls(
            storage=InMemoryStorage(cred_objects),
            auto_refresh=False,
        )

    @classmethod
    def with_encrypted_storage(
        cls,
        base_path: str,
        providers: list[CredentialProvider] | None = None,
        **kwargs: Any,
    ) -> CredentialStore:
        """
        Create a credential store with encrypted file storage.

        Args:
            base_path: Directory for credential files
            providers: List of credential providers
            **kwargs: Additional arguments passed to CredentialStore

        Returns:
            CredentialStore with EncryptedFileStorage
        """
        from .storage import EncryptedFileStorage

        return cls(
            storage=EncryptedFileStorage(base_path),
            providers=providers,
            **kwargs,
        )

    @classmethod
    def with_env_storage(
        cls,
        env_mapping: dict[str, str] | None = None,
        providers: list[CredentialProvider] | None = None,
        **kwargs: Any,
    ) -> CredentialStore:
        """
        Create a credential store with environment variable storage.

        Args:
            env_mapping: Map of credential_id -> env_var_name
            providers: List of credential providers
            **kwargs: Additional arguments passed to CredentialStore

        Returns:
            CredentialStore with EnvVarStorage
        """
        return cls(
            storage=EnvVarStorage(env_mapping),
            providers=providers,
            **kwargs,
        )
