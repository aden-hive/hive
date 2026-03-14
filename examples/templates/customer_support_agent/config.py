"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Customer Support Agent"
    version: str = "1.0.0"
    description: str = (
        "Classify customer queries, generate helpful replies, "
        "and log support tickets automatically."
    )
    intro_message: str = (
        "Hi! I'm your customer support assistant. "
        "Please describe your issue and I'll help you right away."
    )


metadata = AgentMetadata()