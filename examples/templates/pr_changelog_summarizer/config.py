"""Runtime configuration for PR Changelog Summarizer agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


@dataclass
class AgentMetadata:
    name: str = "PR Changelog Summarizer"
    version: str = "1.0.0"
    description: str = (
        "Summarize recent pull requests from a GitHub repository into a "
        "changelog or release notes document."
    )
    intro_message: str = (
        "Hi! I'll help you generate a changelog from a GitHub repository's pull requests. "
        "Share the repo URL (e.g. https://github.com/owner/repo) or owner/repo, "
        "and I'll fetch recent PRs and produce a formatted changelog."
    )


metadata = AgentMetadata()
default_config = RuntimeConfig(temperature=0.2)
