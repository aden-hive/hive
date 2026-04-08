"""Hive Agent Framework.

Core classes:
    AgentHost      -- hosts agents, manages entry points and pipeline
    Orchestrator   -- routes between nodes in a graph
    AgentLoop      -- the LLM + tool execution loop (one per node)
    AgentLoader    -- loads agent.json from disk, builds pipeline
    DecisionTracker -- records decisions for post-hoc analysis
"""

from framework.agent_loop import AgentLoop
from framework.host import AgentHost
from framework.loader import AgentLoader
from framework.orchestrator import Orchestrator
from framework.tracker import DecisionTracker

__all__ = [
    "AgentHost",
    "AgentLoader",
    "AgentLoop",
    "DecisionTracker",
    "Orchestrator",
]
