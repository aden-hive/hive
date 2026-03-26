"""Document Intelligence Agent Team — A2A Queen Bee + Worker Bees template.

First Hive template demonstrating the delegate_to_sub_agent pattern
for multi-agent coordination with cross-reference synthesis.
"""

__version__ = "0.1.0"

from .agent import (
    DocumentIntelligenceAgentTeam,
    default_agent,
    edges,
    goal,
    nodes,
)
from .config import AgentMetadata, default_config, metadata, worker_models
from framework.config import RuntimeConfig

__all__ = [
    "DocumentIntelligenceAgentTeam",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
    "worker_models",
]
