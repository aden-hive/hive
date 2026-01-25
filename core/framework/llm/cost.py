"""LLM cost calculation utilities for tracking API usage costs."""

from typing import ClassVar


class LLMCostCalculator:
    """
    Calculate estimated costs for LLM API calls.

    Pricing is based on publicly available pricing as of January 2025.
    Prices are in USD per 1 million tokens (input, output).

    Note: Prices may change over time. Update this table periodically.
    """

    PRICING: ClassVar[dict[str, tuple[float, float]]] = {
        # OpenAI models (input, output) per 1M tokens
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-2024-11-20": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o-mini-2024-07-18": (0.15, 0.60),
        "gpt-4-turbo": (10.00, 30.00),
        "gpt-4-turbo-2024-04-09": (10.00, 30.00),
        "gpt-4": (30.00, 60.00),
        "gpt-3.5-turbo": (0.50, 1.50),
        "gpt-3.5-turbo-0125": (0.50, 1.50),
        # Anthropic Claude models
        "claude-3-5-sonnet-20241022": (3.00, 15.00),
        "claude-3-5-sonnet-20240620": (3.00, 15.00),
        "claude-3-5-haiku-20241022": (0.80, 4.00),
        "claude-haiku-4-5-20251001": (0.80, 4.00),
        "claude-3-opus-20240229": (15.00, 75.00),
        "claude-3-sonnet-20240229": (3.00, 15.00),
        "claude-3-haiku-20240307": (0.25, 1.25),
        # Google Gemini models
        "gemini-pro": (0.50, 1.50),
        "gemini-1.5-pro": (1.25, 5.00),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini/gemini-pro": (0.50, 1.50),
        "gemini/gemini-1.5-pro": (1.25, 5.00),
        "gemini/gemini-1.5-flash": (0.075, 0.30),
        # Mistral models
        "mistral-large-latest": (0.50, 1.50),
        "mistral-medium-latest": (0.40, 2.00),
        "mistral-small-latest": (0.10, 0.30),
        # Groq models
        "groq/openai/gpt-oss-20b": (0.075, 0.30),
        "groq/openai/gpt-oss-120b": (0.15, 0.075),
        "groq/llama-3.3-70b-versatile": (0.59, 0.79),
        "groq/meta-llama/llama-4-maverick-17b-128e-instruct": (0.20, 0.60)
    }

    @classmethod
    def calculate(
        cls,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Calculate the estimated cost for an LLM API call.

        Args:
            model: Model identifier (e.g., "gpt-4o-mini", "claude-3-5-haiku-20241022")
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens

        Returns:
            Estimated cost in USD. Returns 0.0 if model pricing is not available.
        """
        if model not in cls.PRICING:
            return 0.0 # TODO: Add error handling, or need to let user know the model is not supported for cost calculation

        input_cost_per_1m, output_cost_per_1m = cls.PRICING[model]

        input_cost = (input_tokens * input_cost_per_1m) / 1_000_000
        output_cost = (output_tokens * output_cost_per_1m) / 1_000_000

        return input_cost + output_cost

    @classmethod
    def get_pricing(cls, model: str) -> tuple[float, float] | None:
        """
        Get pricing information for a model.

        Args:
            model: Model identifier

        Returns:
            Tuple of (input_cost_per_1m, output_cost_per_1m) or None if not available
        """
        return cls.PRICING.get(model)

    @classmethod
    def format_cost(cls, cost_usd: float) -> str:
        """
        Format cost for display.

        Args:
            cost_usd: Cost in USD

        Returns:
            Formatted string (e.g., "$0.0042", "$1.23")
        """
        if cost_usd < 0.01:
            return f"${cost_usd:.4f}"
        elif cost_usd < 1.00:
            return f"${cost_usd:.3f}"
        else:
            return f"${cost_usd:.2f}"
