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
    return "groq/llama-3.3-70b-versatile"


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
    name: str = "Blog Writer Agent"
    version: str = "1.0.0"
    description: str = "Generate SEO-optimized blog posts by researching topics, creating structured outlines, and producing polished markdown with citations."


metadata = AgentMetadata()
