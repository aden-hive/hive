"""
LLM-based judge for semantic evaluation of test results.

Used by tests that need to evaluate semantic properties like
"no hallucination" or "preserves meaning" that can't be checked
with simple assertions.

Usage in tests:
    from framework.testing.llm_judge import LLMJudge

    # Default: uses Anthropic (requires ANTHROPIC_API_KEY)
    judge = LLMJudge()
    result = judge.evaluate(
        constraint="no-hallucination",
        source_document="The original text...",
        summary="The summary to evaluate...",
        criteria="Summary must only contain facts from the source"
    )
    assert result["passes"], result["explanation"]

    # With custom LLM provider:
    from framework.llm.litellm import LiteLLMProvider
    judge = LLMJudge(llm_provider=LiteLLMProvider(model="gpt-4o-mini"))
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider


class LLMJudge:
    """
    LLM-based judge for semantic evaluation of test results.

    Uses an LLM to evaluate whether outputs meet semantic constraints
    that can't be verified with simple assertions.

    Supports any LLMProvider (Anthropic, OpenAI, LiteLLM, etc.) or falls
    back to Anthropic for backward compatibility.
    """

    def __init__(self, llm_provider: LLMProvider | None = None):
        """
        Initialize the LLM judge.

        Args:
            llm_provider: Optional LLM provider instance. If not provided,
                          falls back to Anthropic client (requires ANTHROPIC_API_KEY).
        """
        self._provider = llm_provider
        self._client = None  # Fallback Anthropic client (lazy-loaded)

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.Anthropic()
            except ImportError as err:
                raise RuntimeError("anthropic package required for LLM judge") from err
        return self._client

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
            # Use injected provider if available
            if self._provider is not None:
                response = self._provider.complete(
                    messages=[{"role": "user", "content": prompt}],
                    system="",
                    max_tokens=500,
                    json_mode=True,
                )
                text = response.content.strip()
            else:
                # Fallback to Anthropic (backward compatible)
                client = self._get_client()
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()

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
