"""Runtime configuration."""

import json
from dataclasses import dataclass, field
from pathlib import Path


def _load_preferred_model() -> str:
    """Load preferred model from ~/.hive/configuration.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            llm = config.get("llm", {})
            if llm.get("provider") and llm.get("model"):
                return f"{llm['provider']}/{llm['model']}"
        except Exception:
            pass
    return "anthropic/claude-sonnet-4-20250514"


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.7
    max_tokens: int = 8192
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


# Agent metadata
@dataclass
class AgentMetadata:
    name: str = "Online Research Agent"
    version: str = "1.0.0"
    description: str = "Research any topic by searching multiple sources, synthesizing information, and producing a well-structured narrative report with citations."


metadata = AgentMetadata()
