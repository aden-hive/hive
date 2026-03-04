from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List

from ..config import HIGH_RISK_COUNTRIES, RISK_THRESHOLDS


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def run(state: Dict[str, Any]) -> NodeResult:
    vendor = (state or {}).get("vendor", {})
    vendor_type = (state or {}).get("vendor_type", "other")
    compliance = (state or {}).get("compliance", {})
    missing_fields = (state or {}).get("missing_fields", [])

    score = 0
    reasons: List[str] = []

    # Country risk
    country = (vendor.get("country") or "").strip()
    if country in HIGH_RISK_COUNTRIES:
        score += 60
        reasons.append(f"High-risk country: {country}")

    # Vendor type risk
    if vendor_type == "payment_processor":
        score += 25
        reasons.append("Payment processing vendor type")
    elif vendor_type in ("data_provider", "security_vendor"):
        score += 15
        reasons.append(f"Sensitive vendor type: {vendor_type}")

    # Missing docs or fields increase risk
    if missing_fields:
        score += min(30, 5 * len(missing_fields))
        reasons.append(f"Missing required fields: {', '.join(missing_fields)}")

    missing_docs = (compliance.get("missing_docs") or [])
    if missing_docs:
        score += min(30, 5 * len(missing_docs))
        reasons.append(f"Missing compliance documents: {', '.join(missing_docs)}")

    # Contract value heuristic
    acv = vendor.get("annual_contract_value")
    if isinstance(acv, (int, float)) and acv >= 100000:
        score += 10
        reasons.append("High contract value (>= 100k)")

    # Clamp
    score = max(0, min(100, score))

    # Map to level
    if score >= RISK_THRESHOLDS["high"]:
        level = "high"
    elif score >= RISK_THRESHOLDS["medium"]:
        level = "medium"
    else:
        level = "low"

    new_state = dict(state or {})
    new_state["risk"] = {"score": score, "level": level, "reasons": reasons}
    new_state["audit"].append({"node": "risk", "event": "scored_risk", "score": score, "level": level})

    return NodeResult(ok=True, data=new_state, notes=f"Risk={level} ({score})")
