"""LLM provider pipeline stage.

Resolves the LLM provider from global config. This is the ONLY place
the LLM gets created for worker agents.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("llm_provider")
class LlmProviderStage(PipelineStage):
    """Resolve LLM provider and make it available."""

    order = 10

    def __init__(
        self,
        model: str | None = None,
        mock_mode: bool = False,
        llm: Any = None,
        **kwargs: Any,
    ) -> None:
        self._model = model
        self._mock_mode = mock_mode
        self.llm = llm  # Pre-injected LLM (e.g. from session)

    async def initialize(self) -> None:
        if self.llm is not None:
            return  # Already injected

        from framework.config import (
            get_api_key,
            get_api_keys,
            get_hive_config,
            get_preferred_model,
        )

        model = self._model or get_preferred_model()

        if self._mock_mode:
            from framework.llm.mock import MockLLMProvider

            self.llm = MockLLMProvider(model=model)
            return

        config = get_hive_config()
        llm_config = config.get("llm", {})
        api_base = llm_config.get("api_base")

        # Check for Antigravity (special provider)
        if llm_config.get("use_antigravity_subscription"):
            try:
                from framework.llm.antigravity import AntigravityProvider

                provider = AntigravityProvider(model=model)
                if provider.has_credentials():
                    self.llm = provider
                    logger.info("[pipeline] LlmProviderStage: Antigravity")
                    return
            except Exception:
                pass

        from framework.llm.litellm import LiteLLMProvider

        api_key = get_api_key()
        api_keys = get_api_keys()

        if api_keys and len(api_keys) > 1:
            self.llm = LiteLLMProvider(
                model=model,
                api_keys=api_keys,
                api_base=api_base,
            )
        elif api_key:
            extra = {}
            if api_key.startswith("sk-ant-oat"):
                extra["extra_headers"] = {"authorization": f"Bearer {api_key}"}
            self.llm = LiteLLMProvider(
                model=model,
                api_key=api_key,
                api_base=api_base,
                **extra,
            )
        else:
            self.llm = LiteLLMProvider(model=model, api_base=api_base)

        logger.info("[pipeline] LlmProviderStage: %s", model)

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        return PipelineResult(action="continue")
