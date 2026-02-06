"""Runtime configuration for Marketing Content Agent."""

from dataclasses import dataclass, field
import os

@dataclass
class RuntimeConfig:
    # This pulls 'groq/llama-3.3-70b-versatile' from your .env
    model: str = os.getenv("LITELLM_MODEL", "groq/llama-3.3-70b-versatile")
    max_tokens: int = 2048
    storage_path: str = "~/.hive/storage"
    mock_mode: bool = False

@dataclass
class AgentMetadata:
    name: str = "marketing_agent"
    version: str = "0.1.0"
    description: str = "Multi-channel marketing content generator"
    author: str = ""
    tags: list[str] = field(
        default_factory=lambda: ["marketing", "content", "template"]
    )

default_config = RuntimeConfig()
metadata = AgentMetadata()