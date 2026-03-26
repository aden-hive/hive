"""Agent graph construction for Release Notes Generator Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal

from .nodes import (
    intake_node,
    collect_changes_node,
    classify_changes_node,
    generate_notes_node,
)

# Goal definition
goal = Goal(
    id="release-notes-generation",
    name="Release Notes Generation",
    description="Generate structured release notes from commits or pull request titles.",
)

# Node list
nodes = [
    intake_node,
    collect_changes_node,
    classify_changes_node,
    generate_notes_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-collect",
        source="intake",
        target="collect_changes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="collect-to-classify",
        source="collect_changes",
        target="classify_changes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-generate",
        source="classify_changes",
        target="generate_notes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph config
entry_node = "intake"

entry_points = {
    "start": "intake"
}

pause_nodes = []

terminal_nodes = [
    "generate_notes"
]
