"""Configuration for Release Notes Generator Agent."""


class RuntimeConfig:
    """Runtime configuration for the agent."""

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-20250514",
        api_key: str | None = None,
        api_base: str | None = None,
        max_tokens: int = 2000,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.max_tokens = max_tokens


class AgentMetadata:
    """Metadata for the agent."""

    def __init__(
        self,
        name: str = "Release Notes Generator Agent",
        version: str = "1.0.0",
        description: str = "Generate structured release notes from commits or pull request titles.",
    ):
        self.name = name
        self.version = version
        self.description = description


# Default instances
default_config = RuntimeConfig()
metadata = AgentMetadata()
