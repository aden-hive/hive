"""Credential-store adapter for MCP auth token lookup."""

from __future__ import annotations

import logging

from framework.credentials import CredentialStore
from framework.mcp.auth.models import MCPAuthToken

logger = logging.getLogger(__name__)


class MCPTokenStore:
    """Finds reusable bearer tokens from existing credential storage."""

    TOKEN_KEYS = ("access_token", "token", "bearer_token")

    def __init__(self, store: CredentialStore | None = None):
        self._store = store

    def _get_store(self) -> CredentialStore | None:
        if self._store is not None:
            return self._store
        try:
            self._store = CredentialStore.with_aden_sync(auto_sync=False)
        except Exception:
            logger.debug("Credential store unavailable for MCP token lookup", exc_info=True)
            self._store = None
        return self._store

    def resolve_token(self, credential_candidates: list[str]) -> MCPAuthToken | None:
        store = self._get_store()
        if store is None:
            return None

        for credential_id in credential_candidates:
            if not credential_id:
                continue
            try:
                cred = store.get_credential(credential_id)
            except Exception:
                logger.debug(
                    "Failed reading credential '%s' for MCP token lookup",
                    credential_id,
                    exc_info=True,
                )
                continue

            if cred is None:
                continue

            for key_name in self.TOKEN_KEYS:
                token = cred.get_key(key_name)
                if token:
                    return MCPAuthToken(
                        value=token,
                        credential_id=credential_id,
                        key_name=key_name,
                    )
        return None
