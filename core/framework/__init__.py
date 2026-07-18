"""Hive Agent Framework.

Core classes:
    ColonyRuntime -- orchestrates parallel worker clones in a colony
    AgentLoop      -- the LLM + tool execution loop (one per worker)
    AgentLoader    -- loads agent config from disk, builds pipeline
    DecisionTracker -- records decisions for post-hoc analysis
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
    "ColonyRuntime": ("framework.host", "ColonyRuntime"),
    "AgentLoader": ("framework.loader", "AgentLoader"),
    "AgentLoop": ("framework.agent_loop", "AgentLoop"),
    "DecisionTracker": ("framework.tracker", "DecisionTracker"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
