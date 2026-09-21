"""Configuration for xAPI Learning Record Agent."""

import os
from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    """Runtime configuration for the agent."""

    model: str | None = None  # Use system default
    max_tokens: int = 4096
    api_key: str | None = None
    api_base: str | None = None
    verbose: bool = False


# Default runtime configuration
default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    """Agent metadata for identification and display."""

    name: str = "xAPI Learning Record Agent"
    version: str = "0.1.0"
    description: str = (
        "A deterministic, LRS-integrated agent that captures learning events, "
        "builds valid xAPI 1.0.3 statements, validates structure, dispatches to "
        "an LRS via HTTP Basic auth, and returns a confirmation with statement_id."
    )
    intro_message: str = (
        "xAPI Learning Record Agent\n\n"
        "I record learning events as xAPI statements and dispatch them to your LRS.\n"
        "Provide a learning event (actor, verb, object, result) and I will:\n"
        "- Build a valid xAPI 1.0.3 statement\n"
        "- Validate required fields, URI format, and score range\n"
        "- POST to your LRS via HTTP Basic auth\n"
        "- Return a confirmation with statement_id and timestamp\n\n"
        "No LLM required — this pipeline is fully deterministic."
    )
    tags: list[str] = field(
        default_factory=lambda: [
            "xapi",
            "lrs",
            "learning-records",
            "edtech",
            "deterministic",
            "no-llm",
        ]
    )


# LRS connection settings — loaded from environment variables
LRS_ENDPOINT = os.environ.get("LRS_ENDPOINT", "")
LRS_USERNAME = os.environ.get("LRS_USERNAME", "")
LRS_PASSWORD = os.environ.get("LRS_PASSWORD", "")

# Platform identifier embedded in xAPI context
PLATFORM = "Hive"

# Default metadata instance
metadata = AgentMetadata()
