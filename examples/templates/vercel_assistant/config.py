"""Configuration for Vercel Assistant Agent."""

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class AgentMetadata:
    """Agent metadata."""

    id: str = "vercel_assistant"
    name: str = "Vercel Assistant"
    version: str = "1.0.0"
    description: str = (
        "Interactive assistant for managing Vercel deployments, projects, "
        "and environment variables through natural language commands."
    )


@dataclass
class RuntimeConfig:
    """Runtime configuration."""

    model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    api_base: str | None = os.getenv("ANTHROPIC_API_BASE", None)
    max_steps: int = 50
    max_retries: int = 3
    checkpoint_dir: Path | None = None

    def __post_init__(self):
        if self.checkpoint_dir is None:
            self.checkpoint_dir = (
                Path.home() / ".hive" / "checkpoints" / "vercel_assistant"
            )


metadata = AgentMetadata()
default_config = RuntimeConfig()
