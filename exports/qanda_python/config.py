"""Runtime configuration for the Q&A Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

# Default configuration instance
default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    """Metadata for the Q&A Agent.

    Attributes:
        name: The display name of the agent.
        version: The version string of the agent.
        description: A brief summary of what the agent does.
        intro_message: The message shown when the agent starts.
    """
    name: str = "Q&A Agent (Python)"
    version: str = "1.0.0"
    description: str = (
        "A simple Q&A agent designed to answer questions understandably and clearly."
    )
    intro_message: str = (
        "Hello! I am your Q&A Agent. Ask me anything, and I'll do my best to provide a clear answer."
    )


# Metadata instance
metadata = AgentMetadata()
