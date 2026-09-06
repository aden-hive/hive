"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Email Reply Agent"
    version: str = "1.0.0"
    description: str = "Filter unreplied emails, confirm recipients, send personalized replies."
    intro_message: str = (
        "Tell me which emails you want to reply to (e.g., 'emails from @company.com in the last week')."
    )


metadata = AgentMetadata()
