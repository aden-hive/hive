"""Runtime configuration for Support Debugger Agent."""

from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    model: str = "anthropic/claude-sonnet-4-20250514"
    max_tokens: int = 4096
    api_key: str | None = None
    api_base: str | None = None
    storage_path: str = "~/.hive/support_debugger"
    mock_mode: bool = False


@dataclass
class AgentMetadata:
    name: str = "support_debugger"
    version: str = "0.1.0"
    description: str = "Hypothesis-driven support ticket debugging agent"
    author: str = ""
    tags: list[str] = field(
        default_factory=lambda: ["support", "debugging", "investigation", "template"]
    )


default_config = RuntimeConfig()
metadata = AgentMetadata()
