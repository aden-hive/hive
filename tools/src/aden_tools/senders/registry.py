"""Sender pool loader + cache.

Pulls the team's senders from the Aden cloud (``GET /v1/senders/runtime``)
using the same ``ADEN_API_KEY`` + base URL the credential sync already uses,
and caches them with a short TTL (the cloud is the source of truth; a fresh
sender shows up within one TTL, or immediately after :meth:`refresh`).

For OAuth senders the row only carries an ``integration_id``; the actual
access token is resolved on demand through the existing credential path
(``GET /v1/credentials/{integration_id}``) so tokens are never duplicated in
the senders store.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_ADEN_BASE_URL_DEFAULT = "https://app.open-hive.com"

# Short, because this cache gates a SAFETY rail. daily_limit lives on the sender
# row, so a stale cache means a limit the user just tightened isn't enforced yet
# — and over-sending from a cold-outbound domain is not undoable. 60s bounds the
# window to one extra cloud GET per minute while senders are in use.
_DEFAULT_TTL_SECONDS = 60.0


@dataclass
class SenderConfig:
    """One sender the agent can send from."""

    id: str
    name: str
    provider: str  # google | mailjet | sendgrid | hubspot
    auth_type: str  # oauth | api_key
    from_email: str
    from_name: str | None = None
    integration_id: str | None = None
    secret: dict[str, Any] | None = None
    weight: int = 1
    daily_limit: int | None = None
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    can_receive: bool = False
    """True when this sender has an inbox the reply poller can watch."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SenderConfig:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            provider=str(d.get("provider", "")),
            auth_type=str(d.get("auth_type", "")),
            from_email=str(d.get("from_email", "")),
            from_name=d.get("from_name"),
            integration_id=d.get("integration_id"),
            secret=d.get("secret") if isinstance(d.get("secret"), dict) else None,
            weight=int(d.get("weight", 1) or 0),
            daily_limit=(int(d["daily_limit"]) if d.get("daily_limit") is not None else None),
            enabled=bool(d.get("enabled", True)),
            tags=list(d.get("tags") or []),
            can_receive=bool(d.get("can_receive", False)),
        )

    def public_view(self) -> dict[str, Any]:
        """Secret-free view for listing to the agent/UI."""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "auth_type": self.auth_type,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "weight": self.weight,
            "daily_limit": self.daily_limit,
            "enabled": self.enabled,
            "tags": self.tags,
            "can_receive": self.can_receive,
        }


class SenderRegistry:
    """Loads and caches the team sender pool from Aden cloud."""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._cache: list[SenderConfig] = []
        self._loaded_at: float = 0.0
        self._client: Any | None = None

    # -- cloud client -------------------------------------------------------
    def _get_client(self) -> Any | None:
        if not os.environ.get("ADEN_API_KEY"):
            return None
        if self._client is not None:
            return self._client
        try:
            from framework.credentials.aden import AdenClientConfig, AdenCredentialClient

            self._client = AdenCredentialClient(
                AdenClientConfig(
                    base_url=os.environ.get("ADEN_API_URL", _ADEN_BASE_URL_DEFAULT),
                    timeout=5.0,
                )
            )
        except Exception as e:  # pragma: no cover - defensive
            log.warning("Sender registry: Aden client unavailable: %s", e)
            self._client = None
        return self._client

    def cloud(self) -> Any | None:
        """The Aden cloud client, or None when the device has no API key.

        Public so the setup flow (:mod:`setup`) can create senders through the
        same authenticated client the pool is loaded with.
        """
        return self._get_client()

    # -- loading ------------------------------------------------------------
    def _stale(self) -> bool:
        return (time.time() - self._loaded_at) >= self._ttl

    def _load(self) -> None:
        client = self._get_client()
        if client is None:
            self._cache = []
            self._loaded_at = time.time()
            return
        try:
            rows = client.list_team_senders()
            self._cache = [SenderConfig.from_dict(r) for r in rows if isinstance(r, dict)]
        except Exception as e:
            log.warning("Sender registry: failed to load senders: %s", e)
            # Keep the previous cache on a transient failure rather than
            # wiping the pool mid-campaign.
            if not self._cache:
                self._cache = []
        self._loaded_at = time.time()

    def refresh(self) -> None:
        """Force an immediate reload from cloud (used after config changes)."""
        self._loaded_at = 0.0
        self._load()

    def _ensure_loaded(self) -> None:
        if self._loaded_at == 0.0 or self._stale():
            self._load()

    # -- queries ------------------------------------------------------------
    def list(self, include_disabled: bool = False) -> list[SenderConfig]:
        self._ensure_loaded()
        if include_disabled:
            return list(self._cache)
        return [s for s in self._cache if s.enabled]

    def get(self, id_or_name: str) -> SenderConfig | None:
        """Resolve a sender by id (exact) or name (case-insensitive)."""
        self._ensure_loaded()
        for s in self._cache:
            if s.id == id_or_name:
                return s
        lowered = id_or_name.strip().lower()
        for s in self._cache:
            if s.name.strip().lower() == lowered:
                return s
        return None

    def resolve_oauth_token(self, sender: SenderConfig) -> str | None:
        """Resolve a fresh access token for an OAuth sender, or None."""
        if sender.auth_type != "oauth" or not sender.integration_id:
            return None
        client = self._get_client()
        if client is None:
            return None
        try:
            cred = client.get_credential(sender.integration_id)
            return cred.access_token if cred else None
        except Exception as e:
            log.warning("Sender registry: token resolve failed for %s: %s", sender.id, e)
            return None


_REGISTRY: SenderRegistry | None = None


def get_registry() -> SenderRegistry:
    """Process-wide sender registry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SenderRegistry()
    return _REGISTRY
