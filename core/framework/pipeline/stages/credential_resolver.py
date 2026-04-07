"""Credential resolver pipeline stage.

Resolves connected accounts from the credential store and builds
the ``accounts_prompt`` and ``tool_provider_map`` for system prompt
injection.  Replaces the credential resolution block in
``AgentLoader._setup()`` (lines 1861-1879).
"""

from __future__ import annotations

import logging
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("credential_resolver")
class CredentialResolverStage(PipelineStage):
    """Resolve connected accounts and inject into pipeline context."""

    order = 40  # before MCP (tools need account info for routing)

    def __init__(self, **kwargs: Any) -> None:
        self._accounts_prompt = ""
        self._accounts_data: list[dict] | None = None
        self._tool_provider_map: dict[str, str] | None = None

    async def initialize(self) -> None:
        """Resolve credentials from the store."""
        try:
            from aden_tools.credentials.store_adapter import (
                CredentialStoreAdapter,
            )
            from framework.orchestrator.prompting import build_accounts_prompt

            adapter = CredentialStoreAdapter.default()
            self._accounts_data = adapter.get_all_account_info()
            self._tool_provider_map = adapter.get_tool_provider_map()
            if self._accounts_data:
                self._accounts_prompt = build_accounts_prompt(
                    self._accounts_data,
                    self._tool_provider_map,
                )
        except Exception:
            pass  # best-effort -- agent works without account info

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Inject credential info into pipeline context."""
        ctx.metadata["accounts_prompt"] = self._accounts_prompt
        ctx.metadata["accounts_data"] = self._accounts_data
        ctx.metadata["tool_provider_map"] = self._tool_provider_map
        return PipelineResult(action="continue")
