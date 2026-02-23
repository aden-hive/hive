"""Runtime configuration for Hive Coder agent."""

from dataclasses import dataclass, field

from framework.config import get_preferred_model, get_max_tokens, get_api_key, get_api_base


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)


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
