"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Twitter Outreach Agent"
    version: str = "1.0.0"
    description: str = (
        "Reads a target's Twitter/X profile, crafts a personalized outreach email "
        "referencing their specific activity, and sends it after user approval."
    )


metadata = AgentMetadata()
