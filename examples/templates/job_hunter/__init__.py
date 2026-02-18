"""
Job Hunter Agent - Parse resumes, score for ATS, research market demand,
find matching jobs, and generate tailored application materials.

Parse your resume to identify your strongest role fits, score it for ATS
compatibility, search for matching job opportunities, and generate
ATS-optimized resume customization lists and cold outreach emails
for each position you select.
"""

from .agent import JobHunterAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "2.0.0"

__all__ = [
    "JobHunterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
