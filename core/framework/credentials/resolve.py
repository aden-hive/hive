"""Resolve a fresh secret for ``hive-cred token`` and internal callers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from framework.credentials.models import CredentialExpiredError, CredentialObject, CredentialType


@dataclass(frozen=True)
class ResolvedSecret:
    credential_id: str
    account: str | None
    key: str
    value: str
    expires_at: datetime | None
    credential_type: str | None

    @property
    def expires_in_seconds(self) -> int | None:
        if self.expires_at is None:
            return None
        return max(0, int((self.expires_at - datetime.now(UTC)).total_seconds()))

    @property
    def is_oauth(self) -> bool:
        return self.credential_type == CredentialType.OAUTH2.value


class SecretNotFound(LookupError):
    """No value exists for the requested credential / account / key."""


def _default_key_name(cred: CredentialObject) -> str | None:
    # Mirrors CredentialObject.get_default_key's priority so the expiry we
    # report belongs to the same key whose value we return.
    for name in ("value", "api_key", "access_token"):
        if name in cred.keys:
            return name
    for name in cred.keys:
        if not name.startswith("_"):
            return name
    return next(iter(cred.keys), None)


def _from_credential(cred: CredentialObject, account: str | None, key: str) -> ResolvedSecret | None:
    key_name = key or _default_key_name(cred)
    if key_name is None:
        return None
    ck = cred.keys.get(key_name)
    if ck is None:
        return None
    return ResolvedSecret(
        credential_id=cred.id,
        account=account or cred.alias,
        key=key_name,
        value=ck.get_secret_value(),
        expires_at=ck.expires_at,
        credential_type=str(cred.credential_type) if cred.credential_type else None,
    )


def resolve_secret(adapter: Any, credential_id: str, account: str = "", key: str = "") -> ResolvedSecret:
    """Return a fresh secret for ``credential_id`` (optionally one ``account``).

    Resolution checks locally collected accounts first, then the encrypted
    store. Store hits are re-fetched through
    ``get_credential(..., raise_on_refresh_failure=True)`` so an expired OAuth
    token is refreshed before it is returned.

    Raises:
        SecretNotFound: nothing stored under that id / account / key.
        CredentialExpiredError: the token is expired and refresh failed —
            the caller should tell the user to reconnect, not retry.
    """
    from framework.credentials.local.registry import LocalCredentialRegistry

    store = adapter.store

    if account:
        try:
            local = LocalCredentialRegistry.default().get_key(credential_id, account, key or "api_key")
        except Exception:
            local = None
        if local is not None:
            return ResolvedSecret(credential_id, account, key or "api_key", local, None, None)
        cred = store.get_credential_by_alias(credential_id, account)
        if cred is None:
            raise SecretNotFound(f"{credential_id}/{account}")
        # The alias lookup is a raw storage load; go back through
        # get_credential so refresh-on-access fires (same as store_adapter.get_by_alias).
        fresh = store.get_credential(cred.id, raise_on_refresh_failure=True) or cred
        resolved = _from_credential(fresh, account, key)
        if resolved is None:
            raise SecretNotFound(f"{credential_id}/{account} key {key!r}")
        return resolved

    cred = store.get_credential(credential_id, raise_on_refresh_failure=True)
    if cred is not None:
        resolved = _from_credential(cred, None, key)
        if resolved is not None:
            return resolved

    # No account given and nothing in the store: fall back to a collected
    # local account (sole account, or one aliased "default").
    registry = LocalCredentialRegistry.default()
    accounts = registry.list_accounts(credential_id)
    target = None
    if len(accounts) == 1:
        target = accounts[0].alias
    elif any(a.alias == "default" for a in accounts):
        target = "default"
    if target is not None:
        local = registry.get_key(credential_id, target, key or "api_key")
        if local is not None:
            return ResolvedSecret(credential_id, target, key or "api_key", local, None, None)
    raise SecretNotFound(credential_id + (f" key {key!r}" if key else ""))


__all__ = ["CredentialExpiredError", "ResolvedSecret", "SecretNotFound", "resolve_secret"]
