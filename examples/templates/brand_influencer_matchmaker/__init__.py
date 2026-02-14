"""
Brand-Influencer Matchmaker Agent - Autonomous affinity scoring & sales briefs.

Analyzes brand websites and influencer content to calculate a compatibility score
and generate a strategic sales briefing doc to aid partnership decisions.
"""

from .agent import BrandInfluencerMatchmakerAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "BrandInfluencerMatchmakerAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
