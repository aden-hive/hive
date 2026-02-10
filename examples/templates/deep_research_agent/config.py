"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Deep Research Agent"
    version: str = "1.0.0"
    description: str = (
        "Interactive research agent that rigorously investigates topics through "
        "multi-source search, quality evaluation, and synthesis - with TUI conversation "
        "at key checkpoints for user guidance and feedback."
    )


metadata = AgentMetadata()
