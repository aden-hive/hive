"""Runtime configuration for LinkedIn ABM Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


@dataclass
class AgentMetadata:
    name: str = "LinkedIn ABM Agent"
    version: str = "1.0.0"
    description: str = (
        "Multi-channel Account-Based Marketing automation. "
        "Prospect LinkedIn leads, enrich with Apollo, and execute "
        "coordinated outreach via email, LinkedIn, and direct mail."
    )


metadata = AgentMetadata()
default_config = RuntimeConfig(temperature=0.3)
