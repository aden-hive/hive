"""Runtime configuration for Brand-Influencer Matchmaker."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Brand-Influencer Matchmaker"
    version: str = "1.0.0"
    description: str = (
        "Autonomous sales-enablement agent that analyzes brand websites and "
        "influencer content to calculate a compatibility score (0-100) and "
        "generate a strategic partnership briefing document."
    )
    intro_message: str = (
        "Hello! I'm your Brand-Influencer Matchmaker. I help sales teams validate "
        "partnerships by analyzing brand alignment. Please provide a **Brand URL** "
        "and an **Influencer Name/Handle**, and I'll generate a data-backed "
        "compatibility score and sales brief for you."
    )


metadata = AgentMetadata()
