"""Runtime configuration for Hive Coder agent."""

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
    max_tokens: int = 40000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Hive Coder"
    version: str = "1.0.0"
    description: str = (
        "Native coding agent that builds production-ready Hive agent packages "
        "from natural language specifications. Deeply understands the agent framework "
        "and produces complete Python packages with goals, nodes, edges, system prompts, "
        "MCP configuration, and tests."
    )
    intro_message: str = (
        "I'm Hive Coder — I build Hive agents. Describe what kind of agent "
        "you want to create and I'll design, implement, and validate it for you."
    )


metadata = AgentMetadata()
