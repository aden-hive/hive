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
    intro_message: str = (
        "Hi! I can help you with personalized Twitter outreach. Give me a Twitter/X "
        "handle and I'll analyze their profile, then craft a tailored outreach email "
        "for your approval."
    )


metadata = AgentMetadata()
