"""Runtime configuration for Job Hunter Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Job Hunter"
    version: str = "2.0.0"
    description: str = (
        "Parse your resume, score it for ATS compatibility, identify errors and gaps, "
        "research live market demand for your skills, find matching job opportunities, "
        "and generate ATS-optimized resume customizations and cold outreach emails "
        "for each position you select."
    )
    intro_message: str = (
        "Welcome to Job Hunter Pro. Upload your resume and this pipeline will: "
        "parse it for structure and errors, score it against each job for ATS compatibility, "
        "research live market demand for your skills, find 10 matched job openings, "
        "and generate tailored resume edits and cold outreach emails for the roles you choose."
    )


metadata = AgentMetadata()
