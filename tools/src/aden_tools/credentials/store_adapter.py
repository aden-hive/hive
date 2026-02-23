"""
Adapter to integrate the new CredentialStore with the existing CredentialManager API.

This provides backward compatibility, allowing existing tools to work unchanged
while enabling new features (template resolution, multi-key credentials, etc.).

Usage:
    from framework.credentials import CredentialStore
    from aden_tools.credentials.store_adapter import CredentialStoreAdapter

    # Create new credential store
    store = CredentialStore.with_encrypted_storage()  # defaults to ~/.hive/credentials

    # Wrap with adapter for backward compatibility
    credentials = CredentialStoreAdapter(store)

    # Existing API works unchanged
    api_key = credentials.get("brave_search")
    credentials.validate_for_tools(["web_search"])

    # New features also available
    headers = credentials.resolve_headers({
        "Authorization": "Bearer {{github_oauth.access_token}}"
    })
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import CredentialError, CredentialSpec

if TYPE_CHECKING:
    from framework.credentials import CredentialStore


class CredentialStoreAdapter:
    """
    Adapter that makes CredentialStore compatible with existing CredentialManager API.

    This class provides the same interface as CredentialManager while using
    the new CredentialStore for storage and resolution.

    Features:
    - Full backward compatibility with existing CredentialManager API
    - New template resolution capabilities
    - Access to multi-key credentials
    - Access to underlying CredentialStore for advanced usage

    Migration path:
    1. Replace CredentialManager() with CredentialStoreAdapter(store)
    2. Existing code continues to work
    3. Gradually adopt new features (template resolution, etc.)
    """

    def __init__(
        self,
        store: CredentialStore,
        specs: dict[str, CredentialSpec] | None = None,
    ):
        """
        Initialize the adapter.

        Args:
            store: The CredentialStore to wrap
            specs: Credential specifications for validation. Defaults to CREDENTIAL_SPECS.
        """
        if specs is None:
            from . import CREDENTIAL_SPECS

            specs = CREDENTIAL_SPECS

        self._store = store
        self._specs = specs

        # Build reverse mappings for validation
        self._tool_to_cred: dict[str, str] = {}
        self._node_type_to_cred: dict[str, str] = {}

        for cred_name, spec in self._specs.items():
            for tool_name in spec.tools:
                self._tool_to_cred[tool_name] = cred_name
            for node_type in spec.node_types:
                self._node_type_to_cred[node_type] = cred_name

    # --- Existing CredentialManager API ---

    def get(self, name: str, account: str | None = None) -> str | None:
        """
        Get a credential value by logical name.

        This is the primary method for retrieving credentials.
        For multi-key credentials, returns the default key (api_key, access_token, etc.).

        Args:
            name: Logical credential name (e.g., "brave_search")
            account: Optional alias for per-call routing to a specific named local
                account (e.g. "work"). When provided, looks up the named account
                from LocalCredentialRegistry before falling through to the store.
                This mirrors the ``account=`` routing available for Aden credentials.

        Returns:
            The credential value, or None if not set

        Raises:
            KeyError: If the credential name is not in specs
        """
        if name not in self._specs:
            raise KeyError(f"Unknown credential '{name}'. Available: {list(self._specs.keys())}")

        if account is not None:
            try:
                from framework.credentials.local.registry import LocalCredentialRegistry

                key = LocalCredentialRegistry.default().get_key(name, account)
                if key is not None:
                    return key
            except Exception:
                pass  # Fall through to standard store lookup

        return self._store.get(name)

    def get_spec(self, name: str) -> CredentialSpec:
        """Get the spec for a credential."""
        if name not in self._specs:
            raise KeyError(f"Unknown credential '{name}'")
        return self._specs[name]

    def is_available(self, name: str) -> bool:
        """Check if a credential is available (set and non-empty)."""
        value = self._store.get(name)
        return value is not None and value != ""

    def get_credential_for_tool(self, tool_name: str) -> str | None:
        """
        Get the credential name required by a tool.

        Args:
            tool_name: Name of the tool (e.g., "web_search")

        Returns:
            Credential name if tool requires one, None otherwise
        """
        return self._tool_to_cred.get(tool_name)

    def get_missing_for_tools(self, tool_names: list[str]) -> list[tuple[str, CredentialSpec]]:
        """
        Get list of missing credentials for the given tools.

        Args:
            tool_names: List of tool names to check

        Returns:
            List of (credential_name, spec) tuples for missing credentials
        """
        missing: list[tuple[str, CredentialSpec]] = []
        checked: set[str] = set()

        for tool_name in tool_names:
            cred_name = self._tool_to_cred.get(tool_name)
            if cred_name is None:
                continue
            if cred_name in checked:
                continue
            checked.add(cred_name)

            spec = self._specs[cred_name]
            if spec.required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        return missing

    def validate_for_tools(self, tool_names: list[str]) -> None:
        """
        Validate that all credentials required by the given tools are available.

        Args:
            tool_names: List of tool names to validate credentials for

        Raises:
            CredentialError: If any required credentials are missing
        """
        missing = self.get_missing_for_tools(tool_names)
        if missing:
            raise CredentialError(self._format_missing_error(missing, tool_names))

    def get_missing_for_node_types(self, node_types: list[str]) -> list[tuple[str, CredentialSpec]]:
        """Get list of missing credentials for the given node types."""
        missing: list[tuple[str, CredentialSpec]] = []
        checked: set[str] = set()

        for node_type in node_types:
            cred_name = self._node_type_to_cred.get(node_type)
            if cred_name is None:
                continue
            if cred_name in checked:
                continue
            checked.add(cred_name)

            spec = self._specs[cred_name]
            if spec.required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        return missing

    def validate_for_node_types(self, node_types: list[str]) -> None:
        """
        Validate that all credentials required by the given node types are available.

        Args:
            node_types: List of node types to validate credentials for

        Raises:
            CredentialError: If any required credentials are missing
        """
        missing = self.get_missing_for_node_types(node_types)
        if missing:
            raise CredentialError(self._format_missing_node_type_error(missing, node_types))

    def validate_startup(self) -> None:
        """
        Validate that all startup-required credentials are present.

        Raises:
            CredentialError: If any startup-required credentials are missing
        """
        missing: list[tuple[str, CredentialSpec]] = []

        for cred_name, spec in self._specs.items():
            if spec.startup_required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        if missing:
            raise CredentialError(self._format_startup_error(missing))

    # --- New CredentialStore Features ---

    def get_key(self, credential_id: str, key_name: str) -> str | None:
        """
        Get a specific key from a multi-key credential.

        Args:
            credential_id: The credential identifier
            key_name: The key within the credential

        Returns:
            The key value or None
        """
        return self._store.get_key(credential_id, key_name)

    def resolve(self, template: str) -> str:
        """
        Resolve credential templates in a string.

        Args:
            template: String containing {{cred.key}} patterns

        Returns:
            Template with all references resolved

        Example:
            >>> credentials.resolve("Bearer {{github.access_token}}")
            "Bearer ghp_xxxxxxxxxxxx"
        """
        return self._store.resolve(template)

    def resolve_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """
        Resolve credential templates in headers dictionary.

        Args:
            headers: Dict of header name to template value

        Returns:
            Dict with all templates resolved

        Example:
            >>> credentials.resolve_headers({
            ...     "Authorization": "Bearer {{github.access_token}}"
            ... })
            {"Authorization": "Bearer ghp_xxx"}
        """
        return self._store.resolve_headers(headers)

    def resolve_params(self, params: dict[str, str]) -> dict[str, str]:
        """Resolve credential templates in query parameters."""
        return self._store.resolve_params(params)

    def list_accounts(self, provider_name: str) -> list[dict]:
        """List all accounts for a provider type."""
        return self._store.list_accounts(provider_name)

    def get_all_account_info(self) -> list[dict]:
        """Collect all accounts across all configured providers.

        Deduplicates by provider name to avoid listing the same provider's
        accounts twice when multiple specs map to the same provider.
        """
        accounts: list[dict] = []
        seen: set[str] = set()
        for name, spec in self._specs.items():
            provider = spec.credential_id or name
            if provider in seen or not self.is_available(name):
                continue
            seen.add(provider)
            accounts.extend(self._store.list_accounts(provider))
        return accounts

    def get_by_alias(self, provider_name: str, alias: str) -> str | None:
        """Resolve a specific account's token by alias."""
        cred = self._store.get_credential_by_alias(provider_name, alias)
        return cred.get_default_key() if cred else None

    def get_by_identity(self, provider_name: str, label: str) -> str | None:
        """Alias for get_by_alias (backward compat)."""
        return self.get_by_alias(provider_name, label)

    # --- Local credential registry ---

    def list_local_accounts(
        self, credential_id: str | None = None
    ) -> list[dict]:
        """
        List named local API key accounts from LocalCredentialRegistry.

        Args:
            credential_id: If given, filter to this credential type only.

        Returns:
            List of account dicts (same shape as Aden account dicts, source='local').
        """
        try:
            from framework.credentials.local.registry import LocalCredentialRegistry

            registry = LocalCredentialRegistry.default()
            return [info.to_account_dict() for info in registry.list_accounts(credential_id)]
        except Exception:
            return []

    def activate_local_account(self, credential_id: str, alias: str) -> bool:
        """
        Inject a named local account's API key into the environment for this session.

        This enables session-level routing: select an account → inject its key as
        the env var that tools already read. No tool signature changes required.

        Args:
            credential_id: Logical credential name (e.g. "brave_search").
            alias: Account alias (e.g. "work").

        Returns:
            True if the key was found and injected, False otherwise.
        """
        import os

        try:
            from framework.credentials.local.registry import LocalCredentialRegistry

            key = LocalCredentialRegistry.default().get_key(credential_id, alias)
            if key is None:
                return False

            spec = self._specs.get(credential_id)
            if spec is None:
                return False

            os.environ[spec.env_var] = key
            return True
        except Exception:
            return False

    @property
    def store(self) -> CredentialStore:
        """Access the underlying credential store for advanced operations."""
        return self._store

    # --- Error Formatting (copied from base.py for consistency) ---

    def _format_missing_error(
        self,
        missing: list[tuple[str, CredentialSpec]],
        tool_names: list[str],
    ) -> str:
        """Format a clear, actionable error message for missing credentials."""
        lines = ["Cannot run agent: Missing credentials\n"]
        lines.append("The following tools require credentials that are not set:\n")

        for _cred_name, spec in missing:
            affected_tools = [t for t in tool_names if t in spec.tools]
            tools_str = ", ".join(affected_tools)

            lines.append(f"  {tools_str} requires {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and re-run the agent.")
        return "\n".join(lines)

    def _format_missing_node_type_error(
        self,
        missing: list[tuple[str, CredentialSpec]],
        node_types: list[str],
    ) -> str:
        """Format a clear, actionable error message for missing node type credentials."""
        lines = ["Cannot run agent: Missing credentials\n"]
        lines.append("The following node types require credentials that are not set:\n")

        for _cred_name, spec in missing:
            affected_types = [t for t in node_types if t in spec.node_types]
            types_str = ", ".join(affected_types)

            lines.append(f"  {types_str} nodes require {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and re-run the agent.")
        return "\n".join(lines)

    def _format_startup_error(
        self,
        missing: list[tuple[str, CredentialSpec]],
    ) -> str:
        """Format a clear, actionable error message for missing startup credentials."""
        lines = ["Server startup failed: Missing required credentials\n"]

        for _cred_name, spec in missing:
            lines.append(f"  {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and restart the server.")
        return "\n".join(lines)

    # --- Factory Methods ---

    @classmethod
    def default(
        cls,
        specs: dict[str, CredentialSpec] | None = None,
    ) -> CredentialStoreAdapter:
        """Create adapter with encrypted storage primary and env var fallback.

        When ADEN_API_KEY is set, builds the store with AdenSyncProvider and
        AdenCachedStorage so that OAuth credentials (Google, HubSpot, Slack)
        auto-refresh via the Aden server.  Non-Aden credentials (brave_search,
        anthropic, resend) still resolve from environment variables.

        When ADEN_API_KEY is not set, behaves identically to before.
        """
        import logging
        import os

        from framework.credentials import CredentialStore
        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )

        log = logging.getLogger(__name__)

        if specs is None:
            from . import CREDENTIAL_SPECS

            specs = CREDENTIAL_SPECS

        env_mapping = {name: spec.env_var for name, spec in specs.items()}

        # --- Aden sync branch ---
        # Note: we don't use CredentialStore.with_aden_sync() here because it
        # only wraps EncryptedFileStorage.  We need CompositeStorage (encrypted
        # + env var fallback) so non-Aden credentials like brave_search still
        # resolve from environment variables.
        aden_api_key = os.environ.get("ADEN_API_KEY")
        if aden_api_key:
            try:
                from framework.credentials.aden import (
                    AdenCachedStorage,
                    AdenClientConfig,
                    AdenCredentialClient,
                    AdenSyncProvider,
                )

                # Local storage: encrypted primary + env var fallback
                encrypted = EncryptedFileStorage()
                env = EnvVarStorage(env_mapping)
                local_composite = CompositeStorage(primary=encrypted, fallbacks=[env])

                # Aden components
                client = AdenCredentialClient(
                    AdenClientConfig(
                        base_url=os.environ.get("ADEN_API_URL", "https://api.adenhq.com"),
                    )
                )
                provider = AdenSyncProvider(client=client)

                # AdenCachedStorage wraps composite, giving Aden priority
                cached_storage = AdenCachedStorage(
                    local_storage=local_composite,
                    aden_provider=provider,
                    cache_ttl_seconds=300,
                )

                store = CredentialStore(
                    storage=cached_storage,
                    providers=[provider],
                    auto_refresh=True,
                )

                # Initial sync: populate local cache from Aden
                try:
                    synced = provider.sync_all(store)
                    log.info("Aden credential sync complete: %d credentials synced", synced)
                except Exception as e:
                    log.warning("Aden initial sync failed (will retry on access): %s", e)

                return cls(store=store, specs=specs)

            except Exception as e:
                log.warning(
                    "Aden credential sync unavailable, falling back to default storage: %s", e
                )

        # --- Default branch (no ADEN_API_KEY or Aden setup failed) ---
        try:
            encrypted = EncryptedFileStorage()
            env = EnvVarStorage(env_mapping)
            composite = CompositeStorage(primary=encrypted, fallbacks=[env])
            store = CredentialStore(storage=composite)
        except Exception as e:
            log.warning("Encrypted credential storage unavailable, falling back to env vars: %s", e)
            store = CredentialStore.with_env_storage(env_mapping)

        return cls(store=store, specs=specs)

    @classmethod
    def for_testing(
        cls,
        overrides: dict[str, str],
        specs: dict[str, CredentialSpec] | None = None,
    ) -> CredentialStoreAdapter:
        """
        Create a CredentialStoreAdapter for testing with mock credentials.

        Args:
            overrides: Dict mapping credential names to test values
            specs: Optional custom specs

        Returns:
            CredentialStoreAdapter pre-configured for testing

        Example:
            credentials = CredentialStoreAdapter.for_testing({"brave_search": "test-key"})
            assert credentials.get("brave_search") == "test-key"
        """
        from framework.credentials import CredentialStore

        # Convert to CredentialStore.for_testing format
        # Simple credentials get a single "api_key" key
        cred_dict = {cred_id: {"api_key": value} for cred_id, value in overrides.items()}

        store = CredentialStore.for_testing(cred_dict)
        return cls(store=store, specs=specs)

    @classmethod
    def with_env_storage(
        cls,
        env_mapping: dict[str, str] | None = None,
        specs: dict[str, CredentialSpec] | None = None,
    ) -> CredentialStoreAdapter:
        """
        Create adapter with environment variable storage (current behavior).

        This creates an adapter that behaves identically to CredentialManager.

        Args:
            env_mapping: Optional custom env var mapping
            specs: Optional custom credential specs

        Returns:
            CredentialStoreAdapter using env vars for storage
        """
        from framework.credentials import CredentialStore

        # Build env mapping from specs if not provided
        if env_mapping is None:
            if specs is None:
                from . import CREDENTIAL_SPECS

                specs = CREDENTIAL_SPECS
            env_mapping = {name: spec.env_var for name, spec in specs.items()}

        store = CredentialStore.with_env_storage(env_mapping)
        return cls(store=store, specs=specs)
