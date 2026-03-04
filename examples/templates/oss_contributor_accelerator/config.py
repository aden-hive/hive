"""Runtime configuration for OSS Contributor Accelerator."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "OSS Contributor Accelerator"
    version: str = "1.0.0"
    description: str = (
        "Find high-leverage issues in an OSS repo, rank them by impact/fit, and "
        "generate an execution-ready contribution brief with PR drafts."
    )
    intro_message: str = (
        "I help you land meaningful OSS contributions fast. Share a repo and I’ll "
        "shortlist high-impact issues, then build a contribution brief you can execute."
    )


metadata = AgentMetadata()
