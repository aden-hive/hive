"""Contract Evaluation Agent package."""

from .agent import ContractEvaluationAgent, default_agent
from .config import default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "ContractEvaluationAgent",
    "default_agent",
    "default_config",
    "metadata",
]
