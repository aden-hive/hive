"""Tests for TokenBudgetStage and its interaction with CostGuardStage.

These tests cover:
- Token estimation from different input shapes (messages, prompt, goal, text)
- Cost calculation against the curated model catalog
- Metadata population (estimated_cost, estimated_prompt_tokens, pricing_model)
- Passthrough behaviour when model or pricing is missing
- End-to-end integration: TokenBudgetStage feeds CostGuardStage
- Model resolution priority (constructor > input_data > metadata)
- Multi-modal message content blocks
"""

from __future__ import annotations

import pytest

from framework.pipeline.stage import PipelineContext, PipelineRejectedError
from framework.pipeline.stages.cost_guard import CostGuardStage
from framework.pipeline.stages.token_budget import (
    TokenBudgetStage,
    _estimate_cost,
    _estimate_tokens,
)
from framework.pipeline.runner import PipelineRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(
    input_data: dict | None = None,
    metadata: dict | None = None,
    entry_point_id: str = "test",
) -> PipelineContext:
    return PipelineContext(
        entry_point_id=entry_point_id,
        input_data=input_data or {},
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Unit tests: _estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_plain_prompt_string(self):
        # 40 chars / 4 = 10 tokens
        tokens = _estimate_tokens({"prompt": "a" * 40})
        assert tokens == 10

    def test_goal_string(self):
        tokens = _estimate_tokens({"goal": "b" * 80})
        assert tokens == 20

    def test_text_string(self):
        tokens = _estimate_tokens({"text": "c" * 20})
        assert tokens == 5

    def test_messages_list_string_content(self):
        messages = [
            {"role": "user", "content": "a" * 80},
            {"role": "assistant", "content": "b" * 40},
        ]
        tokens = _estimate_tokens({"messages": messages})
        # (80 + 40) / 4 = 30
        assert tokens == 30

    def test_messages_list_multimodal_content(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "a" * 40},
                    {"type": "image_url", "url": "https://example.com/img.png"},
                    {"type": "text", "text": "b" * 20},
                ],
            }
        ]
        tokens = _estimate_tokens({"messages": messages})
        # (40 + 20) / 4 = 15  (image block has no text)
        assert tokens == 15

    def test_system_prompt_added_to_messages(self):
        messages = [{"role": "user", "content": "a" * 40}]
        tokens = _estimate_tokens({"messages": messages, "system": "s" * 40})
        # (40 + 40) / 4 = 20
        assert tokens == 20

    def test_empty_input_returns_zero(self):
        assert _estimate_tokens({}) == 0

    def test_empty_string_fields_return_zero(self):
        assert _estimate_tokens({"prompt": "", "goal": "   "}) == 0

    def test_messages_priority_over_prompt(self):
        # "messages" should be used, not "prompt"
        messages = [{"role": "user", "content": "a" * 40}]
        tokens = _estimate_tokens({"messages": messages, "prompt": "b" * 800})
        assert tokens == 10  # only the 40-char message, not the 800-char prompt


# ---------------------------------------------------------------------------
# Unit tests: _estimate_cost
# ---------------------------------------------------------------------------

class TestEstimateCost:
    def test_basic_cost_calculation(self):
        pricing = {"input": 1.0, "output": 5.0}
        # 1000 prompt tokens * $1/M + 500 output tokens * $5/M
        # = $0.001 + $0.0025 = $0.0035
        cost = _estimate_cost(1000, pricing, 500)
        assert abs(cost - 0.0035) < 1e-9

    def test_zero_tokens_returns_zero(self):
        pricing = {"input": 3.0, "output": 15.0}
        assert _estimate_cost(0, pricing, 0) == 0.0

    def test_missing_output_rate_uses_zero(self):
        pricing = {"input": 2.0}
        cost = _estimate_cost(1000, pricing, 500)
        # 1000 * 2.0 / 1_000_000 = 0.002
        assert abs(cost - 0.002) < 1e-9

    def test_anthropic_haiku_ballpark(self):
        # claude-haiku: $0.80/M input, $4.00/M output
        pricing = {"input": 0.80, "output": 4.00}
        # 5000 prompt + 2048 output
        cost = _estimate_cost(5000, pricing, 2048)
        assert 0.001 < cost < 0.02  # rough sanity


# ---------------------------------------------------------------------------
# Unit tests: TokenBudgetStage.process
# ---------------------------------------------------------------------------

class TestTokenBudgetStage:
    @pytest.mark.asyncio
    async def test_populates_estimated_cost(self):
        stage = TokenBudgetStage(model="claude-haiku-4-5-20251001", expected_output_tokens=512)
        ctx = _ctx({"prompt": "a" * 400})  # 100 tokens
        await stage.process(ctx)
        assert "estimated_cost" in ctx.metadata
        assert ctx.metadata["estimated_cost"] > 0

    @pytest.mark.asyncio
    async def test_populates_token_counts(self):
        stage = TokenBudgetStage(model="claude-haiku-4-5-20251001", expected_output_tokens=512)
        ctx = _ctx({"prompt": "a" * 400})
        await stage.process(ctx)
        assert ctx.metadata["estimated_prompt_tokens"] == 100
        assert ctx.metadata["estimated_output_tokens"] == 512

    @pytest.mark.asyncio
    async def test_populates_pricing_model(self):
        stage = TokenBudgetStage(model="claude-haiku-4-5-20251001")
        ctx = _ctx({"prompt": "hello world"})
        await stage.process(ctx)
        assert ctx.metadata.get("pricing_model") == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_skips_when_no_model(self):
        stage = TokenBudgetStage(model=None)
        ctx = _ctx({"prompt": "a" * 400})
        result = await stage.process(ctx)
        assert result.action == "continue"
        assert "estimated_cost" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_skips_when_model_has_no_pricing(self):
        stage = TokenBudgetStage(model="openrouter")  # not a real model id
        ctx = _ctx({"prompt": "a" * 400})
        result = await stage.process(ctx)
        assert result.action == "continue"
        assert "estimated_cost" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_skips_when_no_text_in_input(self):
        stage = TokenBudgetStage(model="claude-haiku-4-5-20251001")
        ctx = _ctx({"unrecognised_key": 42})
        result = await stage.process(ctx)
        assert result.action == "continue"
        assert "estimated_cost" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_model_resolved_from_input_data(self):
        stage = TokenBudgetStage(model=None)
        ctx = _ctx(
            {"prompt": "a" * 400, "model": "claude-haiku-4-5-20251001"}
        )
        await stage.process(ctx)
        assert "estimated_cost" in ctx.metadata

    @pytest.mark.asyncio
    async def test_model_resolved_from_metadata(self):
        stage = TokenBudgetStage(model=None)
        ctx = _ctx(
            {"prompt": "a" * 400},
            metadata={"model": "claude-haiku-4-5-20251001"},
        )
        await stage.process(ctx)
        assert "estimated_cost" in ctx.metadata

    @pytest.mark.asyncio
    async def test_constructor_model_takes_priority_over_input_data(self):
        # Constructor model wins; the model in input_data is ignored
        stage = TokenBudgetStage(model="claude-opus-4-6")
        ctx = _ctx(
            {"prompt": "a" * 400, "model": "claude-haiku-4-5-20251001"}
        )
        await stage.process(ctx)
        assert ctx.metadata["pricing_model"] == "claude-opus-4-6"

    @pytest.mark.asyncio
    async def test_opus_costs_more_than_haiku(self):
        prompt = {"prompt": "a" * 4000}  # 1000 tokens
        ctx_haiku = _ctx(prompt.copy())
        ctx_opus = _ctx(prompt.copy())
        await TokenBudgetStage(model="claude-haiku-4-5-20251001").process(ctx_haiku)
        await TokenBudgetStage(model="claude-opus-4-6").process(ctx_opus)
        assert ctx_opus.metadata["estimated_cost"] > ctx_haiku.metadata["estimated_cost"]

    @pytest.mark.asyncio
    async def test_stage_order_is_250(self):
        assert TokenBudgetStage.order == 250

    @pytest.mark.asyncio
    async def test_always_returns_continue(self):
        # TokenBudgetStage never rejects — that's CostGuardStage's job
        stage = TokenBudgetStage(model="claude-haiku-4-5-20251001")
        ctx = _ctx({"prompt": "a" * 400})
        result = await stage.process(ctx)
        assert result.action == "continue"


# ---------------------------------------------------------------------------
# Integration tests: TokenBudgetStage + CostGuardStage together
# ---------------------------------------------------------------------------

class TestTokenBudgetWithCostGuard:
    @pytest.mark.asyncio
    async def test_request_within_budget_passes(self):
        runner = PipelineRunner([
            TokenBudgetStage(model="claude-haiku-4-5-20251001", expected_output_tokens=512),
            CostGuardStage(max_cost_per_request=1.0),  # very generous
        ])
        ctx = _ctx({"prompt": "a" * 400})  # tiny prompt, cheap model
        result_ctx = await runner.run(ctx)
        assert result_ctx.metadata["estimated_cost"] < 1.0

    @pytest.mark.asyncio
    async def test_expensive_request_rejected(self):
        runner = PipelineRunner([
            TokenBudgetStage(model="claude-opus-4-6", expected_output_tokens=65_000),
            CostGuardStage(max_cost_per_request=0.001),  # $0.001 budget
        ])
        ctx = _ctx({"prompt": "a" * 40_000})  # 10k tokens
        with pytest.raises(PipelineRejectedError) as exc_info:
            await runner.run(ctx)
        assert "CostGuardStage" in str(exc_info.value)
        assert "exceeds budget" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cost_guard_still_passes_when_no_budget_stage(self):
        # Without TokenBudgetStage, CostGuardStage should pass through (no estimate)
        runner = PipelineRunner([
            CostGuardStage(max_cost_per_request=0.0001),
        ])
        ctx = _ctx({"prompt": "a" * 400_000})  # enormous prompt
        result_ctx = await runner.run(ctx)  # should NOT raise
        assert "estimated_cost" not in result_ctx.metadata

    @pytest.mark.asyncio
    async def test_haiku_passes_strict_budget(self):
        # $0.01 budget: Haiku with small prompt should pass
        runner = PipelineRunner([
            TokenBudgetStage(model="claude-haiku-4-5-20251001", expected_output_tokens=512),
            CostGuardStage(max_cost_per_request=0.01),
        ])
        ctx = _ctx({"prompt": "a" * 400})  # 100 tokens
        result_ctx = await runner.run(ctx)
        assert result_ctx.metadata["estimated_cost"] < 0.01

    @pytest.mark.asyncio
    async def test_pipeline_stage_ordering(self):
        token_stage = TokenBudgetStage(model="claude-haiku-4-5-20251001")
        guard_stage = CostGuardStage(max_cost_per_request=1.0)
        runner = PipelineRunner([guard_stage, token_stage])  # intentionally wrong order
        # PipelineRunner sorts by order; token_budget(250) < cost_guard(300)
        stages = runner.stages
        assert stages[0].__class__.__name__ == "TokenBudgetStage"
        assert stages[1].__class__.__name__ == "CostGuardStage"

    @pytest.mark.asyncio
    async def test_messages_format_works_end_to_end(self):
        runner = PipelineRunner([
            TokenBudgetStage(model="claude-haiku-4-5-20251001", expected_output_tokens=256),
            CostGuardStage(max_cost_per_request=1.0),
        ])
        ctx = _ctx({
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Summarise the following document: " + "x" * 2000},
            ]
        })
        result_ctx = await runner.run(ctx)
        assert result_ctx.metadata["estimated_cost"] > 0
        assert result_ctx.metadata["estimated_prompt_tokens"] > 0
