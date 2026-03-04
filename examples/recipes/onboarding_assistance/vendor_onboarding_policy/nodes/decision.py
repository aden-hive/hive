from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def run(state: Dict[str, Any]) -> NodeResult:
    completeness = (state or {}).get("completeness")
    missing_fields: List[str] = (state or {}).get("missing_fields", [])
    compliance = (state or {}).get("compliance", {})
    risk = (state or {}).get("risk", {})

    missing_docs = compliance.get("missing_docs") or []
    risk_level = risk.get("level", "low")

    # Priority routing:
    # 1) incomplete → request_more_info
    # 2) high risk → human_review
    # 3) missing docs → request_more_info
    # 4) else → approve
    if completeness == "incomplete" or missing_fields:
        route = "request_more_info"
        reason = "Missing required fields"
    elif risk_level == "high":
        route = "human_review"
        reason = "High risk vendor requires human review"
    elif missing_docs:
        route = "request_more_info"
        reason = "Missing compliance documents"
    elif risk_level == "medium":
        route = "request_more_info"
        reason = "Medium risk — requires additional evidence"
    else:
        route = "approve"
        reason = "Low risk and compliance satisfied"

    new_state = dict(state or {})
    new_state["decision_route"] = route
    new_state["decision_reason"] = reason
    new_state["audit"].append({"node": "decision", "event": "routed", "route": route, "reason": reason})

    return NodeResult(ok=True, data=new_state, notes=f"Route={route}: {reason}")
