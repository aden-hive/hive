from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List

from ..config import REQUIRED_FIELDS


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def run(state: Dict[str, Any]) -> NodeResult:
    vendor = (state or {}).get("vendor", {})
    missing: List[str] = []

    for field in REQUIRED_FIELDS:
        v = vendor.get(field)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(field)

    new_state = dict(state or {})
    new_state["missing_fields"] = missing
    new_state["completeness"] = "incomplete" if missing else "complete"
    new_state["audit"].append({"node": "validate", "event": "checked_required_fields", "missing": missing})

    return NodeResult(ok=True, data=new_state, notes="Validated required fields")
