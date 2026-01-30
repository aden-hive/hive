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
        """Lazy-load the LiteLLM provider."""
        if self._client is None:
            from framework.llm.litellm import LiteLLMProvider
            # Use Claude Haiku as default for fast/cheap judging, can be overridden by env
            # LiteLLM handles the provider routing
            self._client = LiteLLMProvider(model="claude-3-haiku-20240307")
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
            # Format the prompt
            messages = [{"role": "user", "content": prompt}]
            
            # Get response from LiteLLM provider
            response = client.generate(messages)
            
            # Parse the response text
            text = response.content.strip()
            
            # Handle potential markdown code blocks
            if "```" in text:
                # robust extraction of json block
                parts = text.split("```")
                for part in parts:
                    if part.strip().startswith("json"):
                        text = part.strip()[4:].strip()
                        break
                    elif part.strip().startswith("{"):
                         text = part.strip()
                         break

            result = json.loads(text)
            return {
                "passes": bool(result.get("passes", False)),
                "explanation": result.get("explanation", "No explanation provided"),
            }
        except Exception as e:
            # On error, fail the test with explanation
            return {"passes": False, "explanation": f"LLM judge error: {e}"}
