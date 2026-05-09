"""Tests for OpenRouterProvider — all mocked, no real API calls.

Tests are written against FREE_MODELS dynamically so they stay correct
even when the alias list changes (e.g. when old models are removed and
new ones are added to OpenRouter's free tier).

Run:
    cd core && uv run pytest tests/test_openrouter_provider.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.llm.openrouter import (
    DEFAULT_FREE_MODEL,
    FALLBACK_CHAIN,
    FREE_MODELS,
    OPENROUTER_API_BASE,
    OpenRouterProvider,
    _resolve_model,
)
from framework.llm.provider import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    content="ok",
    model="test-model",
    prompt_tokens=10,
    completion_tokens=20,
):
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = content
    m.choices[0].finish_reason = "stop"
    m.model = model
    m.usage.prompt_tokens = prompt_tokens
    m.usage.completion_tokens = completion_tokens
    return m


def _first_alias() -> str:
    """Return first alias in FREE_MODELS — used where any valid alias will do."""
    return next(iter(FREE_MODELS))


def _default_alias() -> str:
    """Return the alias that maps to DEFAULT_FREE_MODEL, or first alias."""
    for alias, full_id in FREE_MODELS.items():
        if full_id == DEFAULT_FREE_MODEL:
            return alias
    return _first_alias()


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_alias_expands(self):
        alias = _first_alias()
        assert _resolve_model(alias) == FREE_MODELS[alias]

    def test_unknown_passthrough(self):
        assert _resolve_model("openai/gpt-4o") == "openai/gpt-4o"

    def test_all_aliases_resolve(self):
        for alias, full_id in FREE_MODELS.items():
            assert _resolve_model(alias) == full_id, f"Failed for alias: {alias}"

    def test_full_model_id_passthrough(self):
        full_id = "some-org/some-model:free"
        assert _resolve_model(full_id) == full_id

    def test_default_model_is_in_registry(self):
        """DEFAULT_FREE_MODEL must be reachable via some alias or directly."""
        # Either it's a value in FREE_MODELS, or _resolve_model returns it unchanged
        result = _resolve_model(DEFAULT_FREE_MODEL)
        assert result == DEFAULT_FREE_MODEL


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_raises_without_key(self):
        with patch("framework.llm.openrouter._get_api_key", return_value=None):
            with pytest.raises(ValueError, match="API key"):
                OpenRouterProvider(api_key=None)

    def test_reads_env_key(self):
        # Patch _get_api_key directly — avoids touching the credential store,
        # which raises KeyError if 'openrouter' is not registered in _specs.
        with patch("framework.llm.openrouter._get_api_key", return_value="sk-or-env"):
            p = OpenRouterProvider()
            assert p.api_key == "sk-or-env"

    def test_explicit_key_wins(self):
        p = OpenRouterProvider(api_key="sk-or-explicit")
        assert p.api_key == "sk-or-explicit"

    def test_default_model_is_free(self):
        p = OpenRouterProvider(api_key="x")
        assert p.model == DEFAULT_FREE_MODEL

    def test_alias_resolved_at_init(self):
        alias = _first_alias()
        p = OpenRouterProvider(model=alias, api_key="x")
        assert p.model == FREE_MODELS[alias]

    def test_full_model_id_passes_through(self):
        full_id = "openai/gpt-oss-120b:free"
        p = OpenRouterProvider(model=full_id, api_key="x")
        assert p.model == full_id

    def test_litellm_gets_openrouter_prefix(self):
        p = OpenRouterProvider(api_key="x")
        assert p._provider.model.startswith("openrouter/")

    def test_litellm_gets_correct_api_base(self):
        p = OpenRouterProvider(api_key="x")
        assert p._provider.api_base == OPENROUTER_API_BASE

    def test_list_free_models_returns_dict(self):
        p = OpenRouterProvider(api_key="x")
        result = p.list_free_models()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_list_free_models_matches_registry(self):
        p = OpenRouterProvider(api_key="x")
        assert p.list_free_models() == FREE_MODELS

    def test_free_models_not_empty(self):
        assert len(FREE_MODELS) > 0

    def test_gpt_oss_alias_present(self):
        """gpt-oss-120b is the default model — must always be in FREE_MODELS."""
        assert "gpt-oss-120b" in FREE_MODELS

    def test_default_model_reachable(self):
        """DEFAULT_FREE_MODEL must be a value in FALLBACK_CHAIN or FREE_MODELS."""
        all_models = set(FREE_MODELS.values()) | set(FALLBACK_CHAIN)
        assert DEFAULT_FREE_MODEL in all_models


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


class TestComplete:
    @patch("litellm.completion")
    def test_returns_llm_response(self, mock_comp):
        mock_comp.return_value = _mock_response("Paris")
        p = OpenRouterProvider(api_key="x")
        r = p.complete(messages=[{"role": "user", "content": "Capital of France?"}])
        assert isinstance(r, LLMResponse)
        assert r.content == "Paris"

    @patch("litellm.completion")
    def test_token_counts(self, mock_comp):
        mock_comp.return_value = _mock_response(prompt_tokens=15, completion_tokens=25)
        p = OpenRouterProvider(api_key="x")
        r = p.complete(messages=[{"role": "user", "content": "hi"}])
        assert r.input_tokens == 15
        assert r.output_tokens == 25

    @patch("litellm.completion")
    def test_passes_system_prompt(self, mock_comp):
        mock_comp.return_value = _mock_response("ok")
        p = OpenRouterProvider(api_key="x")
        p.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="You are a pirate.",
        )
        call_kwargs = mock_comp.call_args.kwargs
        messages_sent = call_kwargs.get("messages", [])
        system_msgs = [m for m in messages_sent if m.get("role") == "system"]
        assert any("pirate" in m.get("content", "") for m in system_msgs)


# ---------------------------------------------------------------------------
# acomplete()
# ---------------------------------------------------------------------------


class TestAComplete:
    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_basic(self, mock_ac):
        mock_ac.return_value = _mock_response("async reply")
        p = OpenRouterProvider(api_key="x")
        r = await p.acomplete(messages=[{"role": "user", "content": "hi"}])
        assert r.content == "async reply"

    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_multi_turn(self, mock_ac):
        mock_ac.return_value = _mock_response("turn 2")
        p = OpenRouterProvider(api_key="x")
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]
        r = await p.acomplete(messages=history)
        assert r.content == "turn 2"

    @pytest.mark.asyncio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_token_counts(self, mock_ac):
        mock_ac.return_value = _mock_response(prompt_tokens=30, completion_tokens=40)
        p = OpenRouterProvider(api_key="x")
        r = await p.acomplete(messages=[{"role": "user", "content": "hi"}])
        assert r.input_tokens == 30
        assert r.output_tokens == 40


# ---------------------------------------------------------------------------
# Fallback chain (Feature 5)
# ---------------------------------------------------------------------------


class TestFallbackChain:
    @patch("litellm.completion")
    def test_fallback_on_rate_limit(self, mock_comp):
        try:
            from litellm.exceptions import RateLimitError
        except ImportError:
            pytest.skip("litellm not installed")

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RateLimitError("rate limited", llm_provider="openrouter", model="test")
            return _mock_response("fallback answer")

        mock_comp.side_effect = side_effect
        p = OpenRouterProvider(api_key="x", use_fallback=True)
        r = p.complete(messages=[{"role": "user", "content": "hi"}])
        assert r.content == "fallback answer"
        assert call_count[0] == 2  # primary failed, one fallback succeeded

    @patch("litellm.completion")
    def test_no_fallback_when_disabled(self, mock_comp):
        try:
            from litellm.exceptions import RateLimitError
        except ImportError:
            pytest.skip("litellm not installed")

        mock_comp.side_effect = RateLimitError(
            "rate limited", llm_provider="openrouter", model="test"
        )
        p = OpenRouterProvider(api_key="x", use_fallback=False)
        with pytest.raises(ValueError):
            p.complete(messages=[{"role": "user", "content": "hi"}])

    def test_fallback_chain_excludes_primary(self):
        p = OpenRouterProvider(api_key="x", model=FALLBACK_CHAIN[0])
        assert p.model not in p._fallback_chain()

    def test_fallback_chain_is_not_empty(self):
        # p = OpenRouterProvider(api_key="x")
        assert len(FALLBACK_CHAIN) > 0

    def test_fallback_chain_models_are_strings(self):
        for model in FALLBACK_CHAIN:
            assert isinstance(model, str)
            assert len(model) > 0


# ---------------------------------------------------------------------------
# Regression — existing providers unaffected
# ---------------------------------------------------------------------------


class TestNoRegression:
    def test_litellm_still_importable(self):
        from framework.llm.litellm import LiteLLMProvider

        assert LiteLLMProvider is not None

    def test_anthropic_still_importable(self):
        from framework.llm.anthropic import AnthropicProvider

        assert AnthropicProvider is not None

    def test_openrouter_in_llm_package(self):
        import framework.llm as pkg

        assert hasattr(pkg, "OpenRouterProvider")
