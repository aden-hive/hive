from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def _decision_from_state(state: Dict[str, Any]) -> str:
    route = state.get("decision_route")
    if route == "approve":
        return "approved"
    if route == "request_more_info":
        return "needs_more_info"
    if route == "human_review":
        human = state.get("human_review", {}) or {}
        action = (human.get("action") or "request_more_info").lower()
        if action == "approve":
            return "approved"
        if action == "reject":
            return "rejected"
        return "needs_more_info"
    return "needs_more_info"


def run(state: Dict[str, Any]) -> NodeResult:
    vendor = (state or {}).get("vendor", {})
    vendor_type = (state or {}).get("vendor_type", "other")
    completeness = (state or {}).get("completeness", "unknown")
    missing_fields: List[str] = (state or {}).get("missing_fields", [])
    compliance = (state or {}).get("compliance", {})
    risk = (state or {}).get("risk", {})
    decision = _decision_from_state(state or {})

    output = {
        "vendor_name": vendor.get("vendor_name"),
        "country": vendor.get("country"),
        "service_type": vendor.get("service_type"),
        "vendor_type": vendor_type,
        "completeness_status": completeness,
        "missing_fields": missing_fields,
        "compliance_status": compliance.get("status"),
        "missing_documents": compliance.get("missing_docs", []),
        "risk_level": risk.get("level"),
        "risk_score": risk.get("score"),
        "risk_reasons": risk.get("reasons", []),
        "decision": decision,
        "decision_reason": (state or {}).get("decision_reason"),
        "human_review": (state or {}).get("human_review"),
        "audit_trail": (state or {}).get("audit", []),
    }

    new_state = dict(state or {})
    new_state["result"] = output
    new_state["audit"].append({"node": "finalize", "event": "produced_result", "decision": decision})

    return NodeResult(ok=True, data=new_state, notes=f"Final decision: {decision}")
