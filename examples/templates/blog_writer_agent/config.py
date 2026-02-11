"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Blog Writer Agent"
    version: str = "1.0.0"
    description: str = (
        "Business-focused blog writer that researches sources, builds "
        "positioning, drafts content, and publishes a cited Markdown post "
        "with SEO metadata and HITL checkpoints."
    )
    intro_message: str = (
        "Hi! I'm your blog writing assistant. Tell me a topic and I'll research "
        "it, build a strong business thesis, and deliver a polished post with SEO "
        "metadata. What should we write about?"
    )


metadata = AgentMetadata()
