"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Resume Screening Agent"
    version: str = "1.0.0"
    description: str = (
        "An agent that screens and evaluates resumes against job requirements, "
        "providing structured assessments of candidate qualifications and fit."
    )
    intro_message: str = (
        "Hi! I'm your resume screening assistant. Share a resume and job requirements, "
        "and I'll evaluate the candidate's qualifications."
    )


metadata = AgentMetadata()
