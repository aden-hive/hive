"""Hive Agent Framework.

Core classes:
    ColonyRuntime -- orchestrates parallel worker clones in a colony
    AgentLoop      -- the LLM + tool execution loop (one per worker)
    AgentLoader    -- loads agent config from disk, builds pipeline
    DecisionTracker -- records decisions for post-hoc analysis

They are imported when first used, so importing one module of the framework does not load
all of it. Projects built on Hive import its primitives from ``hive``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.agent_loop import AgentLoop
    from framework.host import ColonyRuntime
    from framework.loader import AgentLoader
    from framework.tracker import DecisionTracker

__all__ = [
    "ColonyRuntime",
    "AgentLoader",
    "AgentLoop",
    "DecisionTracker",
]

_EXPORTS = {
    "AgentLoop": "framework.agent_loop",
    "ColonyRuntime": "framework.host",
    "AgentLoader": "framework.loader",
    "DecisionTracker": "framework.tracker",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value  # resolved once
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
