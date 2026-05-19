"""Token budget stage -- estimate request cost and populate ctx.metadata.

This stage bridges the gap between :class:`CostGuardStage` and the rest of
the pipeline.  ``CostGuardStage`` checks ``ctx.metadata["estimated_cost"]``
but nothing in the pipeline ever set that value, so the cost guard was
effectively a no-op for every request.

``TokenBudgetStage`` fixes this by:

1. Counting the approximate prompt token count from ``ctx.input_data``
   (messages, system prompt, or raw text).
2. Looking up the model's ``pricing_usd_per_mtok`` from the curated catalog.
3. Writing the estimated pre-flight cost into ``ctx.metadata["estimated_cost"]``
   so ``CostGuardStage`` (order=300) can enforce the configured budget.

Token estimation uses the widely-adopted 4-chars-per-token heuristic.  It
is intentionally conservative (over-estimates) so the cost guard errs on the
side of caution rather than letting expensive requests through.

Stage ordering::

    LlmProviderStage (10) → CredentialResolverStage (40) → McpRegistryStage (50)
    → SkillRegistryStage (60) → InputValidationStage (100) → RateLimitStage (200)
    → **TokenBudgetStage (250)** → CostGuardStage (300)

``TokenBudgetStage`` runs at order=250, after input validation (so the input
is known-good) and before the cost guard (so the estimate is ready to check).
"""

from __future__ import annotations

import logging
from typing import Any

from framework.llm.model_catalog import get_model_pricing
from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)

# Conservative chars-per-token ratio used by most tokenisation research.
# Over-estimating is intentional: better to reject a borderline request
# than to silently exceed a production budget.
_CHARS_PER_TOKEN: float = 4.0

# Keys inspected in ``ctx.input_data`` when extracting prompt text, in
# priority order.  The first key that yields a non-empty string wins.
_INPUT_TEXT_KEYS: tuple[str, ...] = (
    "messages",   # list[dict] — OpenAI-style chat format
    "prompt",     # str        — raw prompt string
    "text",       # str        — generic text field
    "goal",       # str        — Hive goal description
    "input",      # str        — generic input field
)


def _estimate_tokens(input_data: dict[str, Any]) -> int:
    """Return an approximate token count for ``input_data``.

    Handles both chat-message lists (``{"messages": [...]}``), system prompt
    strings, and plain text fields.  Returns 0 when no recognisable text
    is found — the caller treats a zero estimate as "cannot estimate".
    """
    total_chars = 0

    for key in _INPUT_TEXT_KEYS:
        value = input_data.get(key)
        if value is None:
            continue

        if key == "messages" and isinstance(value, list):
            for msg in value:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total_chars += len(content)
                    elif isinstance(content, list):
                        # Multi-modal content blocks
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                total_chars += len(block.get("text", ""))
            break

        if isinstance(value, str) and value.strip():
            total_chars += len(value)
            break

    # Also count a system prompt if present alongside messages
    system = input_data.get("system")
    if isinstance(system, str):
        total_chars += len(system)

    return max(0, int(total_chars / _CHARS_PER_TOKEN))


def _estimate_cost(
    prompt_tokens: int,
    pricing: dict[str, float],
    expected_output_tokens: int,
) -> float:
    """Return estimated cost in USD.

    Uses the ``input`` rate from *pricing* for prompt tokens and the
    ``output`` rate for the expected output.  Both rates are expressed
    as USD per million tokens (the catalog convention).
    """
    input_rate = pricing.get("input", 0.0)
    output_rate = pricing.get("output", 0.0)
    cost = (prompt_tokens * input_rate + expected_output_tokens * output_rate) / 1_000_000
    return cost


@register("token_budget")
class TokenBudgetStage(PipelineStage):
    """Estimate pre-flight request cost and expose it for :class:`CostGuardStage`.

    Without this stage, ``CostGuardStage`` always passes through because
    ``ctx.metadata["estimated_cost"]`` is never populated.  Install both
    stages together to enable meaningful budget enforcement::

        from framework.pipeline.stages import CostGuardStage, TokenBudgetStage

        runner = PipelineRunner([
            ...,
            TokenBudgetStage(model="claude-haiku-4-5-20251001",
                             expected_output_tokens=2048),
            CostGuardStage(max_cost_per_request=0.05),
        ])

    Args:
        model: The LiteLLM-compatible model identifier used for the run
            (e.g. ``"claude-haiku-4-5-20251001"``).  When ``None`` the
            stage falls back to the ``model`` key in ``ctx.input_data``,
            then ``ctx.metadata``.
        expected_output_tokens: Conservative estimate of how many output
            tokens the agent will produce.  Defaults to 2 048, which is
            large enough to cover most single-turn responses without
            grossly over-pricing long completions.
        warn_threshold: If the estimate exceeds this fraction of the
            budget configured in ``CostGuardStage``, emit a WARNING log
            even if the request is not rejected.  Set to ``None`` to
            disable.  Ignored when no budget is set.
    """

    order = 250  # After InputValidationStage (100), before CostGuardStage (300)

    def __init__(
        self,
        model: str | None = None,
        expected_output_tokens: int = 2_048,
        warn_threshold: float | None = 0.80,
    ) -> None:
        self._model = model
        self._expected_output_tokens = expected_output_tokens
        self._warn_threshold = warn_threshold

    def _resolve_model(self, ctx: PipelineContext) -> str | None:
        """Return the model id from config, input_data, or metadata."""
        if self._model:
            return self._model
        for source in (ctx.input_data, ctx.metadata):
            if isinstance(source, dict):
                model = source.get("model")
                if isinstance(model, str) and model.strip():
                    return model.strip()
        return None

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        model = self._resolve_model(ctx)
        if not model:
            logger.debug("[token_budget] No model resolved; skipping cost estimate")
            return PipelineResult(action="continue")

        pricing = get_model_pricing(model)
        if not pricing:
            logger.debug(
                "[token_budget] No pricing found for model %r; skipping cost estimate",
                model,
            )
            return PipelineResult(action="continue")

        prompt_tokens = _estimate_tokens(ctx.input_data)
        if prompt_tokens == 0:
            logger.debug(
                "[token_budget] Could not extract prompt text from input_data; skipping estimate"
            )
            return PipelineResult(action="continue")

        estimated = _estimate_cost(prompt_tokens, pricing, self._expected_output_tokens)
        ctx.metadata["estimated_cost"] = estimated
        ctx.metadata["estimated_prompt_tokens"] = prompt_tokens
        ctx.metadata["estimated_output_tokens"] = self._expected_output_tokens
        ctx.metadata["pricing_model"] = model

        logger.info(
            "[token_budget] model=%s prompt_tokens~%d output_tokens~%d estimated=$%.6f",
            model,
            prompt_tokens,
            self._expected_output_tokens,
            estimated,
        )

        # Warn when approaching the budget configured in CostGuardStage, if
        # we can infer it.  The budget is not directly accessible here, but
        # the metadata is readable by any downstream observer.
        if self._warn_threshold is not None:
            budget = ctx.metadata.get("max_cost_per_request")
            if isinstance(budget, (int, float)) and budget > 0:
                ratio = estimated / budget
                if ratio >= self._warn_threshold:
                    logger.warning(
                        "[token_budget] Estimated cost $%.6f is %.0f%% of budget $%.4f "
                        "(model=%s, entry_point=%s)",
                        estimated,
                        ratio * 100,
                        budget,
                        model,
                        ctx.entry_point_id,
                    )

        return PipelineResult(action="continue")
