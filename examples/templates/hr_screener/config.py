"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Automated HR Screener"
    version: str = "1.0.0"
    description: str = (
        "Screen PDF resumes against a job description, score and rank candidates, "
        "produce a Top-5 report, and optionally send response emails. "
        "Designed for local LLM usage to keep applicant PII private."
    )
    intro_message: str = (
        "Hi! I'm your HR screening assistant. Give me a job description and a folder "
        "of PDF resumes, and I'll score each candidate, rank them, and produce a clean "
        "report of your top picks. Ready when you are!"
    )


metadata = AgentMetadata()
