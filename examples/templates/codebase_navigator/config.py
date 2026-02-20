"""Runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Codebase Navigator"
    version: str = "1.0.0"
    description: str = (
        "Navigate unfamiliar codebases using file tools only. Asks what you want "
        "to understand, explores structure, searches for relevant files, and synthesizes "
        "answers with file:line citations. No third-party credentials."
    )
    intro_message: str = (
        "Hi! I help you understand codebases. Tell me what you'd like to explore—entry points, "
        "configuration, a specific module, dependencies, etc. I'll map the structure, search for "
        "relevant files, and summarize with citations. What would you like to understand?"
    )


metadata = AgentMetadata()
default_source_path: Path = Path(".")
