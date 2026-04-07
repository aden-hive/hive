"""LLM provider pipeline stage.

Resolves the LLM provider (model, API key, OAuth token) from the
global config and injects it into the pipeline context.  Replaces
the 150-line provider resolution block in ``AgentLoader._setup()``.

Supports all auth methods:
- Claude Code subscription (OAuth token from ~/.claude/.credentials.json)
- Codex subscription (Keychain / ~/.codex/auth.json)
- Kimi Code subscription (~/.kimi/config.toml)
- Antigravity (Google Cloud Code Assist OAuth)
- Environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
- Key pool (multiple keys with rotation)
- Local models (Ollama, no key needed)
"""

from __future__ import annotations

import logging
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("llm_provider")
class LlmProviderStage(PipelineStage):
    """Resolve LLM provider and inject into pipeline context."""

    order = 10  # earliest -- everything else depends on having an LLM

    def __init__(
        self,
        model: str | None = None,
        mock_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        self._model = model
        self._mock_mode = mock_mode
        self._llm: Any = None

    async def initialize(self) -> None:
        """Resolve and create the LLM provider."""
        from framework.config import get_api_key, get_api_keys, get_hive_config, get_preferred_model

        model = self._model or get_preferred_model()

        if self._mock_mode:
            from framework.llm.mock import MockLLMProvider

            self._llm = MockLLMProvider(model=model)
            return

        config = get_hive_config()
        llm_config = config.get("llm", {})
        api_base = llm_config.get("api_base")
        api_key = get_api_key()
        api_keys = get_api_keys()

        from framework.llm.litellm import LiteLLMProvider

        # Check for Antigravity (special provider, not LiteLLM)
        if llm_config.get("use_antigravity_subscription"):
            try:
                from framework.llm.antigravity import AntigravityProvider

                provider = AntigravityProvider(model=model)
                if provider.has_credentials():
                    self._llm = provider
                    return
            except Exception:
                pass

        # Key pool or single key
        if api_keys and len(api_keys) > 1:
            self._llm = LiteLLMProvider(
                model=model,
                api_keys=api_keys,
                api_base=api_base,
            )
        elif api_key:
            # Detect OAuth subscriptions for special headers
            is_claude_oauth = api_key.startswith("sk-ant-oat")
            if is_claude_oauth:
                self._llm = LiteLLMProvider(
                    model=model,
                    api_key=api_key,
                    api_base=api_base,
                    extra_headers={"authorization": f"Bearer {api_key}"},
                )
            else:
                self._llm = LiteLLMProvider(
                    model=model,
                    api_key=api_key,
                    api_base=api_base,
                )
        else:
            # No key -- local models or env var fallback
            self._llm = LiteLLMProvider(
                model=model,
                api_base=api_base,
            )

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Inject LLM provider into pipeline context."""
        if self._llm:
            ctx.metadata["llm"] = self._llm
        return PipelineResult(action="continue")
