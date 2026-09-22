"""
Automated HR Screener - Screen resumes, rank candidates, and send response emails.

Reads PDF resumes locally, scores candidates against a job description,
produces a Top-5 HTML report, and optionally sends personalized emails.
Designed for local LLM usage to keep applicant PII private.
"""

from .agent import HRScreenerAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "HRScreenerAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
