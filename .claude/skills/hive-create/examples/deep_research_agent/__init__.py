"""
Deep Research Agent - Interactive, rigorous research with TUI conversation.

Research any topic through multi-source web search, quality evaluation,
and synthesis. Features client-facing TUI interaction at key checkpoints
for user guidance and iterative deepening.
"""

from .agent import DeepResearchAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "DeepResearchAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
