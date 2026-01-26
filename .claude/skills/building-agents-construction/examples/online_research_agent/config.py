"""Runtime configuration."""
from dataclasses import dataclass


@dataclass
class RuntimeConfig:
    model: str = "groq/moonshotai/kimi-k2-instruct-0905"
    temperature: float = 0.7
    max_tokens: int = 16384
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
