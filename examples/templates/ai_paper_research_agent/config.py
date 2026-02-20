"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "AI Paper Research Agent"
    version: str = "1.0.0"
    description: str = (
        "Autonomous deep-research agent for machine learning papers. "
        "Finds relevant literature, analyzes difficult papers, and delivers "
        "a structured learning brief with actionable study guidance."
    )
    intro_message: str = (
        "Hi! I can deeply analyze AI papers for your research objective. "
        "Share what you want to understand and I will discover, compare, "
        "and explain the key papers."
    )


metadata = AgentMetadata()
