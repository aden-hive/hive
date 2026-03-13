"""Runtime configuration for Code Documentation Generator Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Code Documentation Generator"
    version: str = "1.0.0"
    description: str = (
        "Automated documentation agent that analyzes codebases to generate "
        "comprehensive API documentation, architecture overviews, and usage "
        "guides with interactive HTML output."
    )
    intro_message: str = (
        "Hi! I'm your code documentation generator. Point me at a codebase "
        "and I'll analyze its structure, extract API signatures, and produce "
        "a comprehensive documentation site. What project would you like "
        "me to document?"
    )


metadata = AgentMetadata()
