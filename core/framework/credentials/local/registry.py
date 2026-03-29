"""
Local Credential Registry.

Manages named local API key accounts stored in EncryptedFileStorage.
Mirrors the Aden integration model so local credentials have feature parity:
aliases, identity metadata, status tracking, CRUD, and health validation.

Storage convention:
    {credential_id}/{alias}  →  CredentialObject
    e.g. "brave_search/work" →  { api_key: "BSA-xxx", _alias: "work",
                                   _integration_type: "brave_search",
                                   _status: "active",
                                   _identity_username: "acme", ... }

Usage:
    registry = LocalCredentialRegistry.default()

    # Add a new account
    info, health = registry.save_account("brave_search", "work", "BSA-xxx")
    print(info.status, info.identity.label)

    # List all accounts
    for account in registry.list_accounts():
        print(f"{account.credential_id}/{account.alias}: {account.status}")

    # Get the raw API key for a specific account
    key = registry.get_key("github", "personal")

    # Re-validate a stored account
    result = registry.validate_account("github", "personal")
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.credentials.models import CredentialIdentity, CredentialObject
from framework.credentials.storage import EncryptedFileStorage

from .models import LocalAccountInfo

if TYPE_CHECKING:
    from aden_tools.credentials.health_check import HealthCheckResult

logger = logging.getLogger(__name__)

_SEPARATOR = "/"


class LocalCredentialRegistry:
    """
    Named local API key account store backed by EncryptedFileStorage.

    Provides the same list/save/get/delete/validate surface as the Aden
    client, but for locally-stored API keys.
    """

    def __init__(self, storage: EncryptedFileStorage) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_accounts(self, credential_id: str | None = None) -> list[LocalAccountInfo]:
        """
        List all stored local accounts.

        Args:
            credential_id: If given, filter to this credential type only.

        Returns:
            List of LocalAccountInfo sorted by credential_id then alias.
        """
        all_ids = self._storage.list_all()
        accounts: list[LocalAccountInfo] = []

        for storage_id in all_ids:
            if _SEPARATOR not in storage_id:
                continue  # Skip legacy un-aliased entries

            try:
                cred_obj = self._storage.load(storage_id)
            except Exception as exc:
                logger.debug("Skipping unreadable credential %s: %s", storage_id, exc)
                continue

            if cred_obj is None:
                continue

            info = self._to_account_info(cred_obj)
            if info is None:
                continue

            if credential_id and info.credential_id != credential_id:
                continue

            accounts.append(info)

        return sorted(accounts, key=lambda a: (a.credential_id, a.alias))

    # ------------------------------------------------------------------
    # Save / add
    # ------------------------------------------------------------------

    def save_account(
        self,
        credential_id: str,
        alias: str,
        api_key: str,
        run_health_check: bool = True,
        extra_keys: dict[str, str] | None = None,
    ) -> tuple[LocalAccountInfo, HealthCheckResult | None]:
        """
        Store a named account, optionally validating it first.

        Args:
            credential_id: Logical credential name (e.g. "brave_search").
            alias: User-chosen name (e.g. "work"). Defaults to "default".
            api_key: The raw API key / token value.
            run_health_check: If True, verify the key against the live API
                and extract identity metadata. Failure still saves with
                status="failed" so the user can re-validate later.
            extra_keys: Additional key/value pairs to store (e.g.
                cse_id for google_custom_search).

        Returns:
            (LocalAccountInfo, HealthCheckResult | None)
        """
        alias = alias or "default"
        health_result: HealthCheckResult | None = None
        identity: dict[str, str] = {}
        status = "active"

        if run_health_check:
            try:
                from aden_tools.credentials.health_check import check_credential_health

                kwargs: dict[str, Any] = {}
                if extra_keys and "cse_id" in extra_keys:
                    kwargs["cse_id"] = extra_keys["cse_id"]

                health_result = check_credential_health(credential_id, api_key, **kwargs)
                status = "active" if health_result.valid else "failed"
                identity = health_result.details.get("identity", {})
            except Exception as exc:
                logger.warning("Health check failed for %s/%s: %s", credential_id, alias, exc)
                status = "unknown"

        storage_id = f"{credential_id}{_SEPARATOR}{alias}"
        now = datetime.now(UTC)

        cred_obj = CredentialObject(id=storage_id)
        cred_obj.set_key("api_key", api_key)
        cred_obj.set_key("_alias", alias)
        cred_obj.set_key("_integration_type", credential_id)
        cred_obj.set_key("_status", status)

        if extra_keys:
            for k, v in extra_keys.items():
                cred_obj.set_key(k, v)

        if identity:
            valid_fields = set(CredentialIdentity.model_fields)
            filtered = {k: v for k, v in identity.items() if k in valid_fields}
            if filtered:
                cred_obj.set_identity(**filtered)

        cred_obj.last_refreshed = now if run_health_check else None
        self._storage.save(cred_obj)

        account_info = LocalAccountInfo(
            credential_id=credential_id,
            alias=alias,
            status=status,
            identity=cred_obj.identity,
            last_validated=cred_obj.last_refreshed,
            created_at=cred_obj.created_at,
        )
        return account_info, health_result

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    def get_account(self, credential_id: str, alias: str) -> CredentialObject | None:
        """Load the raw CredentialObject for a specific account."""
        return self._storage.load(f"{credential_id}{_SEPARATOR}{alias}")

    def get_key(self, credential_id: str, alias: str, key_name: str = "api_key") -> str | None:
        """
        Return the stored secret value for a specific account.

        Args:
            credential_id: Logical credential name (e.g. "brave_search").
            alias: Account alias (e.g. "work").
            key_name: Key within the credential (default "api_key").

        Returns:
            The secret value, or None if not found.
        """
        cred = self.get_account(credential_id, alias)
        if cred is None:
            return None
        return cred.get_key(key_name)

    def get_account_info(self, credential_id: str, alias: str) -> LocalAccountInfo | None:
        """Load a LocalAccountInfo for a specific account."""
        cred = self.get_account(credential_id, alias)
        if cred is None:
            return None
        return self._to_account_info(cred)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_account(self, credential_id: str, alias: str) -> bool:
        """
        Remove a stored account.

        Returns:
            True if the account existed and was deleted, False otherwise.
        """
        return self._storage.delete(f"{credential_id}{_SEPARATOR}{alias}")

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate_account(self, credential_id: str, alias: str) -> HealthCheckResult:
        """
        Re-run health check for a stored account and update its status.

        Args:
            credential_id: Logical credential name.
            alias: Account alias.

        Returns:
            HealthCheckResult from the live API check.

        Raises:
            KeyError: If the account doesn't exist.
        """
        from aden_tools.credentials.health_check import HealthCheckResult, check_credential_health

        cred = self.get_account(credential_id, alias)
        if cred is None:
            raise KeyError(f"No local account found: {credential_id}/{alias}")

        api_key = cred.get_key("api_key")
        if not api_key:
            return HealthCheckResult(valid=False, message="No api_key stored for this account")

        try:
            kwargs: dict[str, Any] = {}
            cse_id = cred.get_key("cse_id")
            if cse_id:
                kwargs["cse_id"] = cse_id

            result = check_credential_health(credential_id, api_key, **kwargs)
        except Exception as exc:
            result = HealthCheckResult(
                valid=False,
                message=f"Health check error: {exc}",
                details={"error": str(exc)},
            )

        # Update status and timestamp in-place
        new_status = "active" if result.valid else "failed"
        cred.set_key("_status", new_status)
        cred.last_refreshed = datetime.now(UTC)

        # Re-extract identity if available
        identity = result.details.get("identity", {})
        if identity:
            valid_fields = set(CredentialIdentity.model_fields)
            filtered = {k: v for k, v in identity.items() if k in valid_fields}
            if filtered:
                cred.set_identity(**filtered)

        self._storage.save(cred)
        return result

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> LocalCredentialRegistry:
        """Create a registry using the default encrypted storage at ~/.hive/credentials."""
        return cls(EncryptedFileStorage())

    @classmethod
    def at_path(cls, path: str | Path) -> LocalCredentialRegistry:
        """Create a registry using a custom storage path."""
        return cls(EncryptedFileStorage(base_path=path))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_account_info(self, cred_obj: CredentialObject) -> LocalAccountInfo | None:
        """Build LocalAccountInfo from a CredentialObject."""
        cred_type_key = cred_obj.keys.get("_integration_type")
        if cred_type_key is None:
            return None
        cred_id = cred_type_key.get_secret_value()

        alias_key = cred_obj.keys.get("_alias")
        alias = alias_key.get_secret_value() if alias_key else cred_obj.id.split(_SEPARATOR, 1)[-1]

        status_key = cred_obj.keys.get("_status")
        status = status_key.get_secret_value() if status_key else "unknown"

        return LocalAccountInfo(
            credential_id=cred_id,
            alias=alias,
            status=status,
            identity=cred_obj.identity,
            last_validated=cred_obj.last_refreshed,
            created_at=cred_obj.created_at,
        )
