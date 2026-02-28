"""Runtime configuration for Credential Tester agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


@dataclass
class AgentMetadata:
    name: str = "Credential Tester"
    version: str = "1.0.0"
    description: str = (
        "Test connected accounts by making real API calls. "
        "Pick an account, verify credentials work, and explore available tools."
    )


metadata = AgentMetadata()
default_config = RuntimeConfig(temperature=0.3)
