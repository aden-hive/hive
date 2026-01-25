"""LLM cost calculation utilities for tracking API usage costs."""

from typing import Any
import litellm


class LLMCostCalculator:
    """
    Calculate estimated costs for LLM API calls.

    Delegates to LiteLLM's built-in cost tracking, which maintains
    up-to-date pricing for all supported models. This eliminates the
    need to manually maintain pricing tables.

    See: https://docs.litellm.ai/docs/completion/token_usage
    """

    @classmethod
    def calculate(
        cls,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Calculate the estimated cost for an LLM API call.

        Uses LiteLLM's built-in cost tracking, which maintains up-to-date
        pricing for all supported models. This includes:
        - All model versions and snapshots
        - Prompt caching costs
        - Regional pricing variations

        Args:
            model: Model identifier (e.g., "gpt-5.2", "claude-sonnet-4-5-20250929")
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens

        Returns:
            Estimated cost in USD. Returns 0.0 if model pricing is not available
            or if an error occurs.
        """
        try:
            prompt_cost, completion_cost, total_cost = litellm.cost_per_token(
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            if total_cost is not None:
                return total_cost
            if prompt_cost is not None and completion_cost is not None:
                return prompt_cost + completion_cost
            return 0.0
        except Exception:
            return 0.0

    @classmethod
    def calculate_from_response(cls, response: Any) -> float:
        """
        Calculate cost directly from a LiteLLM response object.

        Args:
            response: LiteLLM completion response object

        Returns:
            Estimated cost in USD. Returns 0.0 if calculation fails.
        """
        try:
            return litellm.completion_cost(completion_response=response)
        except Exception:
            return 0.0

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
