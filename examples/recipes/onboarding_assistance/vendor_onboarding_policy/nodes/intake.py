from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def run(state: Dict[str, Any], inp: Dict[str, Any]) -> NodeResult:
    """
    Normalize incoming vendor request into a clean state object.
    Deterministic: no LLM calls.
    """
    vendor = dict(inp or {})

    # Basic normalization
    for k, v in list(vendor.items()):
        if isinstance(v, str):
            vendor[k] = v.strip()

    vendor.setdefault("documents", [])
    vendor.setdefault("annual_contract_value", None)

    new_state = dict(state or {})
    new_state["vendor"] = vendor
    new_state.setdefault("audit", [])
    new_state["audit"].append({"node": "intake", "event": "normalized_input"})

    return NodeResult(ok=True, data=new_state, notes="Input normalized")
