"""Goal-level criterion judge using LLM evaluation.

Evaluates whether an execution output satisfies a SuccessCriterion
whose metric is 'llm_judge'. Used by OutcomeAggregator to dispatch
criterion evaluation.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.graph.goal import SuccessCriterion
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = (
    "You are evaluating whether an execution output satisfies a success criterion. "
    "Be precise. Evaluate based on the criterion, not on style or verbosity."
)

_JUDGE_PROMPT = """Evaluate whether this output satisfies the success criterion.

CRITERION: {description}
TARGET: {target}

OUTPUT:
{output}

Respond in exactly this JSON format:
{{"met": true or false, "confidence": 0.0 to 1.0, "reason": "brief explanation"}}"""


async def judge_criterion(
    llm: LLMProvider,
    criterion: SuccessCriterion,
    execution_output: Any,
    max_tokens: int = 512,
) -> bool:
    """Evaluate a criterion using an LLM judge.

    Args:
        llm: LLM provider for evaluation.
        criterion: The success criterion to evaluate.
        execution_output: The execution output to judge.
        max_tokens: Token budget for the judge response.

    Returns:
        True if the criterion is met according to the LLM.
    """
    output_str = _format_output(execution_output)

    prompt = _JUDGE_PROMPT.format(
        description=criterion.description,
        target=criterion.target,
        output=output_str,
    )

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": prompt}],
            system=_JUDGE_SYSTEM,
            max_tokens=max_tokens,
            json_mode=True,
            max_retries=1,
        )
        return _parse_judge_response(response.content)
    except Exception as e:
        logger.warning(f"LLM judge failed for criterion {criterion.id}: {e}")
        return False


def _format_output(output: Any) -> str:
    """Format execution output for the judge prompt."""
    if isinstance(output, dict):
        try:
            return json.dumps(output, indent=2, default=str)[:4000]
        except (TypeError, ValueError):
            pass
    text = str(output)
    return text[:4000] if len(text) > 4000 else text


def _parse_judge_response(text: str) -> bool:
    """Parse the LLM judge JSON response, returning whether the criterion is met."""
    try:
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text.strip())
        return bool(result.get("met", False))
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        logger.warning(f"Failed to parse judge response: {e}")
        return False
