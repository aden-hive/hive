from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


VALID_CHOICES = {"approve", "reject", "request_more_info"}


def run(state: Dict[str, Any], human: Dict[str, Any] | None = None) -> NodeResult:
    """
    Human-in-the-loop decision.
    For v1 MVP: consumes an optional 'human' payload:
      {"action": "approve|reject|request_more_info", "notes": "..."}
    If not provided, defaults to request_more_info.
    """
    human = human or {}
    action = (human.get("action") or "request_more_info").strip().lower()
    notes = (human.get("notes") or "").strip()

    if action not in VALID_CHOICES:
        action = "request_more_info"

    new_state = dict(state or {})
    new_state["human_review"] = {"action": action, "notes": notes}
    new_state["audit"].append({"node": "hitl", "event": "human_review", "action": action})

    return NodeResult(ok=True, data=new_state, notes=f"Human decision: {action}")
