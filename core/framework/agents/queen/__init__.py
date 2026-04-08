"""Queen -- the agent builder for the Hive framework."""

from .agent import queen_goal, queen_loop_config
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "queen_goal",
    "queen_loop_config",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
