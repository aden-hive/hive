"""QA Engineer Agent package."""

# On importe les variables depuis agent.py et config.py pour que Hive les trouve
from .agent import default_agent, edges, goal, nodes
from .config import metadata

# On indique à Python ce qui est exposé publiquement
__all__ = [
    "default_agent",
    "edges",
    "goal",
    "metadata",
    "nodes",
]