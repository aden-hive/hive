"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "BizFlow AI"
    version: str = "1.0.0"
    description: str = (
        "Generates multi-pipeline n8n workflows from natural language requirements."
    )
    intro_message: str = "I can generate n8n workflows for business automation. What pipelines do you need?"


metadata = AgentMetadata()