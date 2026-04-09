"""Hive Agent Framework.

Core classes:
    ColonyRuntime -- orchestrates parallel worker clones in a colony
    AgentLoop      -- the LLM + tool execution loop (one per worker)
    AgentLoader    -- loads agent config from disk, builds pipeline
    DecisionTracker -- records decisions for post-hoc analysis
"""

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
