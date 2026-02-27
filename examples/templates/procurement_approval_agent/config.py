"""Configuration for Procurement Approval Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


@dataclass
class AgentMetadata:
    name: str = "Procurement Approval Agent"
    version: str = "1.0.0"
    description: str = "Automates purchase request approval with budget and vendor validation"


metadata = AgentMetadata()
default_config = RuntimeConfig(temperature=0.2)
