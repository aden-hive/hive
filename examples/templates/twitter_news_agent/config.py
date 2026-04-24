"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Twitter News Digest"
    version: str = "1.1.0"
    description: str = "Monitors Twitter feeds and provides a daily news digest, focused on tech news."
    intro_message: str = "I'm ready to fetch the latest tech news from Twitter. Which tech handles should I check?"


metadata = AgentMetadata()
