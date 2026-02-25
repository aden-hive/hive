"""Runtime configuration for Competitive Intelligence Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config: RuntimeConfig = RuntimeConfig()

@dataclass
class AgentMetadata:
    """Metadata for the Competitive Intelligence Agent."""
    name: str = "Competitive Intelligence Agent"
    version: str = "1.0.0"
    description: str = (
        "Monitors competitor websites, news sources, and GitHub repositories "
        "to deliver automated weekly digests with key insights and trend analysis "
        "for product and marketing teams."
    )
    intro_message: str = (
        "Hi! I'm your competitive intelligence assistant. Tell me which competitors "
        "to monitor and what areas to focus on (pricing, features, hiring, partnerships, etc.) "
        "and I'll research them across websites, news, and GitHub to produce a detailed digest."
    )

metadata: AgentMetadata = AgentMetadata()
