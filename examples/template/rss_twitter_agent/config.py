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
    max_tokens: int = 8000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "RSS-to-Twitter Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated content repurposing from RSS feeds to Twitter threads. "
        "Fetches articles from configured RSS feeds, extracts key points, "
        "and generates engaging Twitter threads for user review."
    )


metadata = AgentMetadata()
