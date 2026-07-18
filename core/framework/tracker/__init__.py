"""Tracker layer -- decision/run logging for Builder analysis."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.tracker.decision_tracker import DecisionTracker

__all__ = ["DecisionTracker"]


def __getattr__(name: str) -> Any:
    if name != "DecisionTracker":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module("framework.tracker.decision_tracker")
    value = getattr(module, "DecisionTracker")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
