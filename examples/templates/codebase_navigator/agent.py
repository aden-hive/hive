"""Agent graph construction for Codebase Navigator Agent."""

from __future__ import annotations

import logging
from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion

from .config import default_config, default_source_path, metadata
from .nodes import (
    deliver_node,
    explore_node,
    intake_node,
    search_node,
    synthesize_node,
)
from .sync_repo import sync

logger = logging.getLogger(__name__)

# Goal definition
goal = Goal(
    id="codebase-navigator",
    name="Codebase Navigator",
    description=(
        "Navigate unfamiliar codebases by mapping structure, searching for relevant files, "
        "and synthesizing answers with file:line citations. One-shot run; ends after the report."
    ),
    success_criteria=[
        SuccessCriterion(
            id="structure-mapped",
            description="Repository structure has been explored",
            metric="structure_complete",
            target="true",
            weight=0.5,
        ),
        SuccessCriterion(
            id="citations",
            description="Answers include file:line citations",
            metric="citation_coverage",
            target="100%",
            weight=0.5,
        ),
    ],
    constraints=[
        Constraint(
            id="no-hallucination",
            description="Only use information from explored/read files",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="source-attribution",
            description="Every claim must cite its source with file:line",
            constraint_type="quality",
            category="accuracy",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    explore_node,
    search_node,
    synthesize_node,
    deliver_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-explore",
        source="intake",
        target="explore",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="explore-to-search",
        source="explore",
        target="search",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="search-to-synthesize",
        source="search",
        target="synthesize",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="synthesize-to-deliver",
        source="synthesize",
        target="deliver",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["deliver"]


class CodebaseNavigatorAgent:
    """
    Codebase Navigator — 5-node pipeline.

    Flow: intake -> explore -> search -> synthesize -> deliver
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes

    def info(self) -> dict:
        """Get agent information."""
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {"name": self.goal.name, "description": self.goal.description},
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node,
            "entry_points": self.entry_points,
            "pause_nodes": self.pause_nodes,
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self) -> dict:
        """Validate agent structure."""
        errors: list[str] = []
        warnings: list[str] = []

        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found")

        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(f"Entry point '{ep_id}' references unknown node '{node_id}'")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = CodebaseNavigatorAgent()


def _run_bootstrap_sync() -> None:
    """
    Sync the source codebase into the agent workspace. Runs on module import.
    Ensures the agent explores up-to-date code. Uses default_source_path from cwd.
    """
    source = (Path.cwd() / default_source_path).resolve()
    if not source.exists():
        logger.warning("Bootstrap sync skipped: source path %s does not exist", source)
        return
    try:
        count = sync(source)
        logger.info("Bootstrap sync: copied %d files from %s to workspace", count, source)
    except Exception as e:
        logger.warning("Bootstrap sync failed: %s", e)


# Sync workspace on import so the agent always explores current code
_run_bootstrap_sync()
