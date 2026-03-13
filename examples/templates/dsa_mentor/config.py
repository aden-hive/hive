"""Runtime configuration for DSA Mentor Agent."""

from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 2048
    storage_path: str = "~/.hive/storage"
    mock_mode: bool = False


@dataclass
class AgentMetadata:
    name: str = "dsa_mentor"
    version: str = "0.1.0"
    description: str = "DSA Mentor Agent for algorithm learning"
    author: str = ""
    tags: list[str] = field(
        default_factory=lambda: ["education", "dsa", "algorithms", "mentor", "template"]
    )


default_config = RuntimeConfig()
metadata = AgentMetadata()
