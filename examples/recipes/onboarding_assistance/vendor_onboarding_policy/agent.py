from __future__ import annotations
from typing import Any, Dict, Optional

from .nodes import intake, validate, classify, compliance, risk, decision, hitl, finalize


def run(input_data: Dict[str, Any], human: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Deterministic MVP runner.
    This does not rely on LLM calls so it can be tested without API keys.
    """
    state: Dict[str, Any] = {}

    # 1) Intake
    r = intake.run(state, input_data)
    state = r.data

    # 2) Validate
    r = validate.run(state)
    state = r.data

    # 3) If incomplete, still continue to finalize for structured output
    # 4) Classify
    r = classify.run(state)
    state = r.data

    # 5) Compliance
    r = compliance.run(state)
    state = r.data

    # 6) Risk
    r = risk.run(state)
    state = r.data

    # 7) Decision route
    r = decision.run(state)
    state = r.data

    # 8) HITL if needed
    if state.get("decision_route") == "human_review":
        r = hitl.run(state, human=human)
        state = r.data

    # 9) Finalize
    r = finalize.run(state)
    state = r.data

    return state["result"]
