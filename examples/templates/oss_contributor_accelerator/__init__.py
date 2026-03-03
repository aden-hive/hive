"""OSS Contributor Accelerator template.

A systematic approach to identifying and executing high-impact
open source contributions through a 4-node flow:
1. intake → collect contributor profile and target repo context
2. issue-scout → discover and rank high-leverage issues  
3. selection → human picks 1-3 target issues
4. contribution-pack → generate execution-ready contribution_brief.md
"""

from .agent import OSSContributorAccelerator, goal, graph, metadata
from .config import default_config

__all__ = [
    "OSSContributorAccelerator",
    "goal", 
    "graph",
    "metadata",
    "default_config",
]

__version__ = "1.0.0"
