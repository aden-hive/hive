"""
OSS Lead Intelligence Agent.

Transforms GitHub repository interest signals (stars, forks, contributions)
into qualified CRM contacts with enrichment data and team notifications.

Features:
- Multi-tool CRM integration (GitHub + Apollo + HubSpot + Slack)
- Human-in-the-loop lead review
- Configurable ICP scoring
- Optional email outreach

Usage:
    from oss_lead_intelligence import OSSLeadIntelligenceAgent, default_agent

    agent = OSSLeadIntelligenceAgent()
    result = await agent.run({"repo_urls": ["adenhq/hive"]})
"""

from .agent import (
    OSSLeadIntelligenceAgent,
    conversation_mode,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    identity_prompt,
    loop_config,
    nodes,
    pause_nodes,
    terminal_nodes,
)
from .config import default_config, metadata

__all__ = [
    "OSSLeadIntelligenceAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "default_config",
    "metadata",
]
