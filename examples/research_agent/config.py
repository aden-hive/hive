from __future__ import annotations

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()

@dataclass
class AgentMetadata:
    name: str = "Research + Summary Agent"
    version: str = "1.0.0"
    description: str = (
        "Takes a research query, performs multi-step processing "
        "(information gathering -> key point extraction -> summarization), "
        "and outputs structured insights."
    )

metadata = AgentMetadata()
