"""Tests for the FinOps pricing module."""

from __future__ import annotations

import pytest

from framework.finops.pricing import (
    MODEL_PRICING,
    ModelPricing,
    estimate_cost,
    get_model_pricing,
)


class TestModelPricing:
    """Tests for ModelPricing dataclass."""

    def test_calculate_cost_basic(self):
        """Test basic cost calculation."""
        pricing = ModelPricing(
            input_price=3.00,
            output_price=15.00,
        )

        cost = pricing.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert cost == 18.00

    def test_calculate_cost_with_cache(self):
        """Test cost calculation with cache tokens."""
        pricing = ModelPricing(
            input_price=3.00,
            output_price=15.00,
            cache_write_price=3.75,
            cache_read_price=0.30,
        )

        cost = pricing.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_write_tokens=500_000,
            cache_read_tokens=500_000,
        )

        expected = 3.00 + 15.00 + (3.75 * 0.5) + (0.30 * 0.5)
        assert abs(cost - expected) < 0.001

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        pricing = ModelPricing(
            input_price=3.00,
            output_price=15.00,
        )

        cost = pricing.calculate_cost(
            input_tokens=0,
            output_tokens=0,
        )

        assert cost == 0.0


class TestModelPricingTable:
    """Tests for the MODEL_PRICING table."""

    def test_claude_models_exist(self):
        """Test that Claude models are in the pricing table."""
        assert "claude-3-5-sonnet-20241022" in MODEL_PRICING
        assert "claude-3-5-haiku-20241022" in MODEL_PRICING
        assert "claude-3-opus-20240229" in MODEL_PRICING

    def test_openai_models_exist(self):
        """Test that OpenAI models are in the pricing table."""
        assert "gpt-4o" in MODEL_PRICING
        assert "gpt-4o-mini" in MODEL_PRICING

    def test_gemini_models_exist(self):
        """Test that Gemini models are in the pricing table."""
        assert "gemini-2.0-flash" in MODEL_PRICING
        assert "gemini-1.5-pro" in MODEL_PRICING

    def test_model_pricing_values(self):
        """Test that pricing values are reasonable."""
        claude_sonnet = MODEL_PRICING["claude-3-5-sonnet-20241022"]
        assert claude_sonnet.input_price > 0
        assert claude_sonnet.output_price > 0
        assert claude_sonnet.output_price > claude_sonnet.input_price


class TestGetModelPricing:
    """Tests for get_model_pricing function."""

    def test_exact_match(self):
        """Test exact model name match."""
        pricing = get_model_pricing("claude-3-5-sonnet-20241022")
        assert pricing is not None
        assert pricing.input_price == 3.00

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        pricing = get_model_pricing("CLAUDE-3-5-SONNET-20241022")
        assert pricing is not None

    def test_whitespace_handling(self):
        """Test whitespace handling."""
        pricing = get_model_pricing("  claude-3-5-sonnet-20241022  ")
        assert pricing is not None

    def test_prefix_match(self):
        """Test prefix matching for model variants."""
        pricing = get_model_pricing("claude-3-5-sonnet-20241022-v2")
        assert pricing is not None

    def test_unknown_model(self):
        """Test unknown model returns None."""
        pricing = get_model_pricing("unknown-model-xyz")
        assert pricing is None


class TestEstimateCost:
    """Tests for estimate_cost function."""

    def test_estimate_cost_known_model(self):
        """Test cost estimation for a known model."""
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=100_000,
            output_tokens=50_000,
        )

        expected = (100_000 / 1_000_000) * 3.00 + (50_000 / 1_000_000) * 15.00
        assert abs(cost - expected) < 0.0001

    def test_estimate_cost_with_cache(self):
        """Test cost estimation with cache tokens."""
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=100_000,
            output_tokens=50_000,
            cache_write_tokens=50_000,
            cache_read_tokens=50_000,
        )

        assert cost > 0

    def test_estimate_cost_unknown_model(self):
        """Test cost estimation for unknown model returns 0."""
        cost = estimate_cost(
            model="unknown-model",
            input_tokens=100_000,
            output_tokens=50_000,
        )

        assert cost == 0.0

    def test_estimate_cost_zero_tokens(self):
        """Test cost estimation with zero tokens."""
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=0,
            output_tokens=0,
        )

        assert cost == 0.0

    def test_estimate_cost_large_values(self):
        """Test cost estimation with large token counts."""
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=10_000_000,
            output_tokens=5_000_000,
        )

        expected = (10 * 3.00) + (5 * 15.00)
        assert abs(cost - expected) < 0.01
