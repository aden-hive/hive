"""Credential resolution helpers for Procurement Approval Agent (Hive v0.6+)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class QuickBooksCredentials:
    client_id: str | None
    client_secret: str | None
    realm_id: str | None
    refresh_token: str | None
    environment: str | None
    source: str

    @property
    def has_minimum(self) -> bool:
        return bool(self.client_id and self.client_secret and self.realm_id)


def _parse_credential_ref(ref: str | None) -> tuple[str, str] | None:
    if not ref or "/" not in ref:
        return None
    name, alias = ref.split("/", 1)
    name = name.strip()
    alias = alias.strip()
    if not name or not alias:
        return None
    return name, alias


def _first_non_empty(credential, keys: list[str]) -> str | None:
    for key in keys:
        try:
            value = credential.get_key(key)
        except Exception:
            value = None
        if value:
            return value
    return None


def resolve_quickbooks_credentials(credential_ref: str | None = None) -> QuickBooksCredentials:
    """Resolve QuickBooks credentials from env first, then credential store by name/alias."""
    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET")
    realm_id = os.environ.get("QUICKBOOKS_REALM_ID")
    refresh_token = os.environ.get("QUICKBOOKS_REFRESH_TOKEN")
    environment = os.environ.get("QUICKBOOKS_ENV", "sandbox")
    source = "env"

    effective_ref = credential_ref or os.environ.get("QUICKBOOKS_CREDENTIAL_REF")
    if client_id and client_secret and realm_id:
        return QuickBooksCredentials(
            client_id=client_id,
            client_secret=client_secret,
            realm_id=realm_id,
            refresh_token=refresh_token,
            environment=environment,
            source=source,
        )

    parsed = _parse_credential_ref(effective_ref)
    if not parsed:
        return QuickBooksCredentials(
            client_id=client_id,
            client_secret=client_secret,
            realm_id=realm_id,
            refresh_token=refresh_token,
            environment=environment,
            source=source,
        )

    name, alias = parsed
    try:
        from framework.credentials.store import CredentialStore
    except Exception:
        return QuickBooksCredentials(
            client_id=client_id,
            client_secret=client_secret,
            realm_id=realm_id,
            refresh_token=refresh_token,
            environment=environment,
            source=source,
        )

    base_path = os.environ.get("HIVE_CREDENTIALS_PATH")
    store = CredentialStore.with_encrypted_storage(base_path=base_path)

    credential = store.get_credential(effective_ref, refresh_if_needed=True)
    if credential is None:
        credential = store.get_credential_by_alias(name, alias)
    if credential is None:
        return QuickBooksCredentials(
            client_id=client_id,
            client_secret=client_secret,
            realm_id=realm_id,
            refresh_token=refresh_token,
            environment=environment,
            source=source,
        )

    source = f"credential:{name}/{alias}"
    client_id = client_id or _first_non_empty(
        credential,
        ["client_id", "quickbooks_client_id", "qb_client_id"],
    )
    client_secret = client_secret or _first_non_empty(
        credential,
        ["client_secret", "quickbooks_client_secret", "qb_client_secret"],
    )
    realm_id = realm_id or _first_non_empty(
        credential,
        ["realm_id", "quickbooks_realm_id", "company_id"],
    )
    refresh_token = refresh_token or _first_non_empty(
        credential,
        ["refresh_token", "quickbooks_refresh_token"],
    )
    environment = environment or _first_non_empty(
        credential,
        ["environment", "env", "quickbooks_env"],
    )

    return QuickBooksCredentials(
        client_id=client_id,
        client_secret=client_secret,
        realm_id=realm_id,
        refresh_token=refresh_token,
        environment=environment or "sandbox",
        source=source,
    )

