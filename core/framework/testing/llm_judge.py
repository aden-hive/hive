"""
LLM-based judge for semantic evaluation of test results.

Used by tests that need to evaluate semantic properties like
"no hallucination" or "preserves meaning" that can't be checked
with simple assertions.

Provider-agnostic: Uses LiteLLM to support any LLM provider (OpenAI, Anthropic, 
Google, local models, etc.)

Usage in tests:
    from framework.testing.llm_judge import LLMJudge

    # Default: uses gpt-4o-mini for cost efficiency
    judge = LLMJudge()
    
    # Or specify a model:
    judge = LLMJudge(model="claude-haiku-4-5-20251001")
    judge = LLMJudge(model="gemini/gemini-1.5-flash")
    
    result = judge.evaluate(
        constraint="no-hallucination",
        source_document="The original text...",
        summary="The summary to evaluate...",
        criteria="Summary must only contain facts from the source"
    )
    assert result["passes"], result["explanation"]
"""

import json
from typing import Any

from framework.llm.litellm import LiteLLMProvider


class LLMJudge:
    """
    LLM-based judge for semantic evaluation of test results.

    Provider-agnostic implementation using LiteLLM to support any LLM provider.
    Evaluates whether outputs meet semantic constraints that can't be verified 
    with simple assertions.
    """

    # Default model - cost-effective for evaluation tasks
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, model: str | None = None):
        """
        Initialize the LLM judge.
        
        Args:
            model: LLM model to use for evaluation. Supports any model that LiteLLM
                   supports (OpenAI, Anthropic, Google, local, etc.). 
                   Defaults to gpt-4o-mini for cost efficiency.
        """
        self._model = model or self.DEFAULT_MODEL
        self._provider: LiteLLMProvider | None = None

    def _get_provider(self) -> LiteLLMProvider:
        """Lazy-load the LLM provider."""
        if self._provider is None:
            self._provider = LiteLLMProvider(model=self._model)
        return self._provider

    def evaluate(
        self,
        constraint: str,
        source_document: str,
        summary: str,
        criteria: str,
    ) -> dict[str, Any]:
        """
        Evaluate whether a summary meets a constraint.

        Args:
            constraint: The constraint being tested (e.g., "no-hallucination")
            source_document: The original document
            summary: The generated summary to evaluate
            criteria: Human-readable criteria for evaluation

        Returns:
            Dict with 'passes' (bool) and 'explanation' (str)
        """
        provider = self._get_provider()

        prompt = f"""You are evaluating whether a summary meets a specific constraint.

CONSTRAINT: {constraint}
CRITERIA: {criteria}

SOURCE DOCUMENT:
{source_document}

SUMMARY TO EVALUATE:
{summary}

Evaluate whether the summary meets the constraint. Be strict but fair.

Respond with JSON in this exact format:
{{"passes": true/false, "explanation": "brief explanation of your judgment"}}

Only output the JSON, nothing else."""

        try:
            response = provider.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                json_mode=True,
            )

            # Parse the response
            text = response.content.strip()
            # Handle potential markdown code blocks
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
            return {
                "passes": bool(result.get("passes", False)),
                "explanation": result.get("explanation", "No explanation provided"),
            }
        except Exception as e:
            # On error, fail the test with explanation
            return {"passes": False, "explanation": f"LLM judge error: {e}"}
