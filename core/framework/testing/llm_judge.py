"""
LLM-based judge for semantic evaluation of test results.

Used by tests that need to evaluate semantic properties like
"no hallucination" or "preserves meaning" that can't be checked
with simple assertions.

Usage in tests:
    from framework.testing.llm_judge import LLMJudge

    judge = LLMJudge()
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


class LLMJudge:
    """
    LLM-based judge for semantic evaluation of test results.

    Uses Claude to evaluate whether outputs meet semantic constraints
    that can't be verified with simple assertions.
    """

    def __init__(self):
        """Initialize the LLM judge."""
        self._client = None

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.Anthropic()
            except ImportError:
                raise RuntimeError("anthropic package required for LLM judge") from None
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
        client = self._get_client()

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
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse the response
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
