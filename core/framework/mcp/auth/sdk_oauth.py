"""SDK OAuth integration scaffold (Scope B entrypoint)."""

from __future__ import annotations

from typing import Any


class MCPSDKOAuthFlow:
    """Thin wrapper around SDK OAuth provider (not invoked in Scope A)."""

    def __init__(self) -> None:
        self.provider_cls: Any | None = None
        try:
            # SDK shape may vary by version; keep this isolated.
            from mcp.client.auth import OAuthClientProvider  # type: ignore

            self.provider_cls = OAuthClientProvider
        except Exception:
            self.provider_cls = None

    @property
    def available(self) -> bool:
        return self.provider_cls is not None
