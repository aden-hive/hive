"""Model pricing tables for cost estimation.

Pricing is per 1M tokens (as of Feb 2026). Update these as models change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelPricing:
    """Pricing for a model (per 1M tokens)."""

    input_price: float
    output_price: float
    cache_write_price: float | None = None
    cache_read_price: float | None = None

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for given token counts."""
        cost = 0.0
        cost += (input_tokens / 1_000_000) * self.input_price
        cost += (output_tokens / 1_000_000) * self.output_price
        if self.cache_write_price and cache_write_tokens:
            cost += (cache_write_tokens / 1_000_000) * self.cache_write_price
        if self.cache_read_price and cache_read_tokens:
            cost += (cache_read_tokens / 1_000_000) * self.cache_read_price
        return cost


MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-20250514": ModelPricing(
        input_price=3.00,
        output_price=15.00,
        cache_write_price=3.75,
        cache_read_price=0.30,
    ),
    "claude-3-5-sonnet-20241022": ModelPricing(
        input_price=3.00,
        output_price=15.00,
        cache_write_price=3.75,
        cache_read_price=0.30,
    ),
    "claude-3-5-sonnet-20240620": ModelPricing(
        input_price=3.00,
        output_price=15.00,
    ),
    "claude-3-5-haiku-20241022": ModelPricing(
        input_price=0.80,
        output_price=4.00,
        cache_write_price=1.00,
        cache_read_price=0.08,
    ),
    "claude-3-opus-20240229": ModelPricing(
        input_price=15.00,
        output_price=75.00,
    ),
    "claude-3-sonnet-20240229": ModelPricing(
        input_price=3.00,
        output_price=15.00,
    ),
    "claude-3-haiku-20240307": ModelPricing(
        input_price=0.25,
        output_price=1.25,
    ),
    "gpt-4o": ModelPricing(
        input_price=2.50,
        output_price=10.00,
        cache_write_price=1.25,
        cache_read_price=0.125,
    ),
    "gpt-4o-mini": ModelPricing(
        input_price=0.15,
        output_price=0.60,
        cache_write_price=0.075,
        cache_read_price=0.0075,
    ),
    "gpt-4-turbo": ModelPricing(
        input_price=10.00,
        output_price=30.00,
    ),
    "gpt-4": ModelPricing(
        input_price=30.00,
        output_price=60.00,
    ),
    "gpt-3.5-turbo": ModelPricing(
        input_price=0.50,
        output_price=1.50,
    ),
    "o1": ModelPricing(
        input_price=15.00,
        output_price=60.00,
    ),
    "o1-mini": ModelPricing(
        input_price=1.50,
        output_price=6.00,
    ),
    "o1-preview": ModelPricing(
        input_price=15.00,
        output_price=60.00,
    ),
    "gemini-2.0-flash": ModelPricing(
        input_price=0.10,
        output_price=0.40,
    ),
    "gemini-1.5-pro": ModelPricing(
        input_price=1.25,
        output_price=5.00,
        cache_write_price=0.3125,
        cache_read_price=0.03125,
    ),
    "gemini-1.5-flash": ModelPricing(
        input_price=0.075,
        output_price=0.30,
    ),
    "gemini-1.0-pro": ModelPricing(
        input_price=0.50,
        output_price=1.50,
    ),
    "deepseek-chat": ModelPricing(
        input_price=0.14,
        output_price=0.28,
        cache_write_price=0.014,
        cache_read_price=0.014,
    ),
    "deepseek-reasoner": ModelPricing(
        input_price=0.55,
        output_price=2.19,
    ),
    "cerebras/llama-3.3-70b": ModelPricing(
        input_price=0.60,
        output_price=0.60,
    ),
    "cerebras/llama-3.1-8b": ModelPricing(
        input_price=0.10,
        output_price=0.10,
    ),
}


def get_model_pricing(model: str) -> ModelPricing | None:
    """Get pricing for a model.

    Args:
        model: Model name (e.g., "claude-3-5-sonnet-20241022")

    Returns:
        ModelPricing if found, None otherwise
    """
    normalized = model.lower().strip()
    for key, pricing in MODEL_PRICING.items():
        if key.lower() == normalized or normalized.startswith(key.lower()):
            return pricing
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Estimate cost for a model call.

    Args:
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cache_write_tokens: Number of cache write tokens (optional)
        cache_read_tokens: Number of cache read tokens (optional)

    Returns:
        Estimated cost in USD, or 0.0 if model not found
    """
    pricing = get_model_pricing(model)
    if not pricing:
        return 0.0
    return pricing.calculate_cost(
        input_tokens, output_tokens, cache_write_tokens, cache_read_tokens
    )
