"""Runtime configuration for the OpenRouter agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig
from framework.llm.openrouter import DEFAULT_FREE_MODEL


@dataclass
class AgentMetadata:
    name: str = "OpenRouter Agent"
    version: str = "1.0.0"
    description: str = (
        "General-purpose AI assistant powered by free open-source models "
        "via OpenRouter (Llama, Mistral, Gemma, Qwen, gpt). "
        "No API cost — pick any free model from the model picker."
    )
    intro_message: str = (
        "Hi! I'm running on a free open-source model via OpenRouter. "
        "Ask me anything — I can answer questions, help with analysis, "
        "write code, and search the web."
    )


metadata = AgentMetadata()

# Default config — uses openrouter as provider, free model as default.
# RuntimeConfig reads ~/.hive/configuration.json for user overrides.
default_config = RuntimeConfig(
    model=DEFAULT_FREE_MODEL,
    temperature=0.7,
)
