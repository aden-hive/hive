"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Hive Dev Loop"
    version: str = "1.0.0"
    description: str = (
        "Autonomous Test-Driven Development (TDD) agent that plans, "
        "writes, and tests code iteratively."
    )
    intro_message: str = (
        "Hive Dev Loop initialized. I am your Lead Architect. "
        "Please describe the software module you wish to build, "
        "and I will initiate the TDD lifecycle."
    )


metadata = AgentMetadata()
