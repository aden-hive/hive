"""
Aden Cached Storage.

Storage backend that combines local cache with Aden server fallback.
Provides offline resilience by caching credentials locally while
keeping them synchronized with the Aden server.

Usage:
    from core.framework.credentials import CredentialStore
    from core.framework.credentials.storage import EncryptedFileStorage
    from core.framework.credentials.aden import (
        AdenCredentialClient,
        AdenClientConfig,
        AdenSyncProvider,
        AdenCachedStorage,
    )

    # Configure
    client = AdenCredentialClient(AdenClientConfig(
        base_url=os.environ["ADEN_API_URL"],
        api_key=os.environ["ADEN_API_KEY"],
    ))
    provider = AdenSyncProvider(client=client)

    # Create cached storage
    storage = AdenCachedStorage(
        local_storage=EncryptedFileStorage(),
        aden_provider=provider,
        cache_ttl_seconds=300,  # Re-check Aden every 5 minutes
    )

    # Create store
    store = CredentialStore(
        storage=storage,
        providers=[provider],
        auto_refresh=True,
    )

    # Credentials automatically fetched from Aden on first access
    # Cached locally for 5 minutes
    # Falls back to cache if Aden is unreachable
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..storage import CredentialStorage

if TYPE_CHECKING:
    from ..models import CredentialObject
    from .provider import AdenSyncProvider

logger = logging.getLogger(__name__)


class AdenCachedStorage(CredentialStorage):
    """
    Storage with local cache and Aden server fallback.

    This storage provides:
    - **Reads**: Try local cache first, fallback to Aden if stale/missing
    - **Writes**: Always write to local cache
    - **Offline resilience**: Uses cached credentials when Aden is unreachable
    - **Provider-based lookup**: Match credentials by provider name (e.g., "hubspot")
      when direct ID lookup fails, since Aden uses hash-based IDs internally.

    The cache TTL determines how long to trust local credentials before
    checking with the Aden server for updates. This balances:
    - Performance (fewer network calls)
    - Freshness (tokens stay current)
    - Resilience (works during brief outages)

    Usage:
        storage = AdenCachedStorage(
            local_storage=EncryptedFileStorage(),
            aden_provider=provider,
            cache_ttl_seconds=300,  # 5 minutes
        )

        store = CredentialStore(
            storage=storage,
            providers=[provider],
        )

        # First access fetches from Aden
        # Subsequent accesses use cache until TTL expires
        # Can look up by provider name OR credential ID
        token = store.get_key("hubspot", "access_token")
    """

    def __init__(
        self,
        local_storage: CredentialStorage,
        aden_provider: AdenSyncProvider,
        cache_ttl_seconds: int = 300,
        prefer_local: bool = True,
    ):
        """
        Initialize Aden-cached storage.

        Args:
            local_storage: Local storage backend for caching (e.g., EncryptedFileStorage).
            aden_provider: Provider for fetching from Aden server.
            cache_ttl_seconds: How long to trust local cache before checking Aden.
                              Default is 300 seconds (5 minutes).
            prefer_local: If True, use local cache when available and fresh.
                         If False, always check Aden first.
        """
        self._local = local_storage
        self._aden_provider = aden_provider
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._prefer_local = prefer_local
        self._cache_timestamps: dict[str, datetime] = {}
        # Index: provider name (e.g., "hubspot") -> list of credential hash IDs
        self._provider_index: dict[str, list[str]] = {}
        # Index: "provider:alias" -> credential hash ID (for alias-based routing)
        self._alias_index: dict[str, str] = {}

    def save(self, credential: CredentialObject) -> None:
        """
        Save credential to local cache and update provider index.

        Args:
            credential: The credential to save.
        """
        self._local.save(credential)
        self._cache_timestamps[credential.id] = datetime.now(UTC)
        self._index_provider(credential)
        logger.debug(f"Cached credential '{credential.id}'")

    def load(self, credential_id: str) -> CredentialObject | None:
        """
        Load credential from cache, with Aden fallback and provider-based lookup.

        The loading strategy depends on the `prefer_local` setting:

        If prefer_local=True (default):
        1. Check if local cache exists and is fresh (within TTL)
        2. If fresh, return cached credential
        3. If stale or missing, fetch from Aden
        4. Update local cache with Aden response
        5. If Aden fails, fall back to stale cache

        If prefer_local=False:
        1. Always try to fetch from Aden first
        2. Update local cache with response
        3. Fall back to local cache only if Aden fails

        Provider-based lookup:
        When a provider index mapping exists for the credential_id (e.g.,
        "hubspot" → hash ID), the Aden-synced credential is loaded first.
        This ensures fresh OAuth tokens from Aden take priority over stale
        local credentials (env vars, old encrypted files).

        Args:
            credential_id: The credential identifier or provider name.

        Returns:
            CredentialObject if found, None otherwise.
        """
        # Check provider index first — Aden-synced credentials take priority
        resolved_ids = self._provider_index.get(credential_id)
        if resolved_ids:
            for rid in resolved_ids:
                if rid != credential_id:
                    result = self._load_by_id(rid)
                    if result is not None:
                        logger.info(
                            f"Loaded credential '{credential_id}' via provider index (id='{rid}')"
                        )
                        return result

        # Direct lookup (exact credential_id match)
        return self._load_by_id(credential_id)

    def _load_by_id(self, credential_id: str) -> CredentialObject | None:
        """
        Load credential by exact ID from cache, with Aden fallback.

        Args:
            credential_id: The exact credential identifier.

        Returns:
            CredentialObject if found, None otherwise.
        """
        local_cred = self._local.load(credential_id)

        # If we prefer local and have a fresh cache, use it
        if self._prefer_local and local_cred and self._is_cache_fresh(credential_id):
            logger.debug(f"Using cached credential '{credential_id}'")
            return local_cred

        # Try to fetch from Aden
        try:
            aden_cred = self._aden_provider.fetch_from_aden(credential_id)
            if aden_cred:
                # Update local cache
                self.save(aden_cred)
                logger.debug(f"Fetched credential '{credential_id}' from Aden")
                return aden_cred
        except Exception as e:
            logger.warning(f"Failed to fetch '{credential_id}' from Aden: {e}")

            # Fall back to local cache if Aden fails
            if local_cred:
                logger.info(f"Using stale cached credential '{credential_id}'")
                return local_cred

        # Return local credential if it exists (may be None)
        return local_cred

    def load_all_for_provider(self, provider_name: str) -> list[CredentialObject]:
        """Load all credentials for a given provider type.

        Args:
            provider_name: Provider name (e.g. "google", "slack").

        Returns:
            List of CredentialObjects for all accounts of this provider.
        """
        results: list[CredentialObject] = []
        for cid in self._provider_index.get(provider_name, []):
            cred = self._load_by_id(cid)
            if cred:
                results.append(cred)
        return results

    def delete(self, credential_id: str) -> bool:
        """
        Delete credential from local cache.

        Note: This does NOT delete the credential from the Aden server.
        It only removes the local cache entry.

        Args:
            credential_id: The credential identifier.

        Returns:
            True if credential existed and was deleted.
        """
        self._cache_timestamps.pop(credential_id, None)
        return self._local.delete(credential_id)

    def list_all(self) -> list[str]:
        """
        List credentials from local cache.

        Returns:
            List of credential IDs in local cache.
        """
        return self._local.list_all()

    def exists(self, credential_id: str) -> bool:
        """
        Check if credential exists in local cache (by ID or provider name).

        Args:
            credential_id: The credential identifier or provider name.

        Returns:
            True if credential exists locally.
        """
        if self._local.exists(credential_id):
            return True
        # Check provider index
        resolved_ids = self._provider_index.get(credential_id)
        if resolved_ids:
            for rid in resolved_ids:
                if rid != credential_id and self._local.exists(rid):
                    return True
        return False

    def _is_cache_fresh(self, credential_id: str) -> bool:
        """
        Check if local cache is still fresh (within TTL).

        Args:
            credential_id: The credential identifier.

        Returns:
            True if cache is fresh, False if stale or not cached.
        """
        cached_at = self._cache_timestamps.get(credential_id)
        if cached_at is None:
            return False
        return datetime.now(UTC) - cached_at < self._cache_ttl

    def invalidate_cache(self, credential_id: str) -> None:
        """
        Invalidate cache for a specific credential.

        The next load() call will fetch from Aden regardless of TTL.

        Args:
            credential_id: The credential identifier.
        """
        self._cache_timestamps.pop(credential_id, None)
        logger.debug(f"Invalidated cache for '{credential_id}'")

    def invalidate_all(self) -> None:
        """Invalidate all cache entries."""
        self._cache_timestamps.clear()
        logger.debug("Invalidated all cache entries")

    def _index_provider(self, credential: CredentialObject) -> None:
        """
        Index a credential by its provider/integration type and alias.

        Aden credentials carry an ``_integration_type`` key whose value is
        the provider name (e.g., ``hubspot``).  This method maps that
        provider name to the credential's hash ID so that subsequent
        ``load("hubspot")`` calls resolve to the correct credential.

        Also indexes by ``_alias`` for alias-based multi-account routing.

        Args:
            credential: The credential to index.
        """
        integration_type_key = credential.keys.get("_integration_type")
        if integration_type_key is None:
            return
        provider_name = integration_type_key.value.get_secret_value()
        if provider_name:
            if provider_name not in self._provider_index:
                self._provider_index[provider_name] = []
            if credential.id not in self._provider_index[provider_name]:
                self._provider_index[provider_name].append(credential.id)
            logger.debug(f"Indexed provider '{provider_name}' -> '{credential.id}'")

            # Index by alias for multi-account routing
            alias_key = credential.keys.get("_alias")
            if alias_key:
                alias = alias_key.value.get_secret_value()
                if alias:
                    self._alias_index[f"{provider_name}:{alias}"] = credential.id

    def load_by_alias(self, provider_name: str, alias: str) -> CredentialObject | None:
        """Load a credential by provider name and alias.

        Args:
            provider_name: Provider type (e.g. "google", "slack").
            alias: User-set alias from the Aden platform.

        Returns:
            CredentialObject if found, None otherwise.
        """
        cred_id = self._alias_index.get(f"{provider_name}:{alias}")
        if cred_id:
            return self._load_by_id(cred_id)
        return None

    def rebuild_provider_index(self) -> int:
        """
        Rebuild the provider and alias indexes from all locally cached credentials.

        Useful after loading from disk when the in-memory indexes are empty.

        Returns:
            Number of provider mappings indexed.
        """
        self._provider_index.clear()
        self._alias_index.clear()
        indexed = 0
        for cred_id in self._local.list_all():
            cred = self._local.load(cred_id)
            if cred:
                before = len(self._provider_index)
                self._index_provider(cred)
                if len(self._provider_index) > before:
                    indexed += 1
        logger.debug(f"Rebuilt provider index with {indexed} mappings")
        return indexed

    def sync_all_from_aden(self) -> int:
        """
        Sync all credentials from Aden server to local cache.

        Calls GET /v1/credentials to list active integrations,
        then fetches tokens for each.

        Returns:
            Number of credentials synced.
        """
        synced = 0

        try:
            integrations = self._aden_provider._client.list_integrations()

            for info in integrations:
                if info.status != "active":
                    logger.warning(f"Skipping integration '{info.alias}': status={info.status}")
                    continue

                try:
                    cred = self._aden_provider.fetch_from_aden(info.integration_id)
                    if cred:
                        self.save(cred)
                        synced += 1
                        logger.info(f"Synced credential '{info.alias}' from Aden")
                except Exception as e:
                    logger.warning(f"Failed to sync '{info.alias}': {e}")

        except Exception as e:
            logger.error(f"Failed to list integrations from Aden: {e}")

        return synced

    def get_cache_info(self) -> dict[str, dict]:
        """
        Get cache status information for all credentials.

        Returns:
            Dict mapping credential_id to cache info (cached_at, is_fresh, ttl_remaining).
        """
        now = datetime.now(UTC)
        info = {}

        for cred_id in self.list_all():
            cached_at = self._cache_timestamps.get(cred_id)
            if cached_at:
                ttl_remaining = (cached_at + self._cache_ttl - now).total_seconds()
                info[cred_id] = {
                    "cached_at": cached_at.isoformat(),
                    "is_fresh": ttl_remaining > 0,
                    "ttl_remaining_seconds": max(0, ttl_remaining),
                }
            else:
                info[cred_id] = {
                    "cached_at": None,
                    "is_fresh": False,
                    "ttl_remaining_seconds": 0,
                }

        return info
