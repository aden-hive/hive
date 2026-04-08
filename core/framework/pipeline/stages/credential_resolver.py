"""Credential resolver pipeline stage.

Resolves connected accounts at startup. Individual credential TTL/refresh
is handled by MCP server processes internally -- they resolve tokens from
the credential store on every tool call.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("credential_resolver")
class CredentialResolverStage(PipelineStage):
    """Resolve connected accounts for system prompt injection."""

    order = 40

    def __init__(self, credential_store: Any = None, **kwargs: Any) -> None:
        self._credential_store = credential_store
        self.accounts_prompt = ""
        self.accounts_data: list[dict] | None = None
        self.tool_provider_map: dict[str, str] | None = None

    async def initialize(self) -> None:
        try:
            from aden_tools.credentials.store_adapter import (
                CredentialStoreAdapter,
            )
            from framework.orchestrator.prompting import build_accounts_prompt

            if self._credential_store is not None:
                adapter = CredentialStoreAdapter(store=self._credential_store)
            else:
                adapter = CredentialStoreAdapter.default()
            self.accounts_data = adapter.get_all_account_info()
            self.tool_provider_map = adapter.get_tool_provider_map()
            if self.accounts_data:
                self.accounts_prompt = build_accounts_prompt(
                    self.accounts_data, self.tool_provider_map,
                )
            logger.info(
                "[pipeline] CredentialResolverStage: %d accounts",
                len(self.accounts_data or []),
            )
        except Exception:
            logger.debug(
                "Credential resolution failed (non-fatal)", exc_info=True,
            )

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        return PipelineResult(action="continue")
