"""Runtime configuration for Curriculum Research Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Curriculum Research Agent"
    version: str = "1.0.0"
    description: str = (
        "Generate ID-ready content briefs for course and program development "
        "using domain-targeted research and ADDIE framework alignment. "
        "Accepts a topic, audience level, and accreditation context, then "
        "produces a structured content brief with learning objectives, "
        "module outlines, assessment types, and curated resources."
    )
    intro_message: str = (
        "Hi! I'm your Curriculum Research assistant. Give me a topic, "
        "target audience, and any accreditation requirements, and I'll "
        "research current industry standards, align findings to learning "
        "outcomes, and produce a structured content brief ready for "
        "instructional design. Let's get started — what program or course "
        "are you developing?"
    )


metadata = AgentMetadata()
