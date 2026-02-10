"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Tech & AI News Reporter"
    version: str = "1.0.0"
    description: str = (
        "Research the latest technology and AI news from the web, "
        "summarize key stories, and produce a well-organized report "
        "for the user to read."
    )


metadata = AgentMetadata()
