"""Quick test script for initialize_agent_package."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from framework.builder.package_generator import (
    BuildSession,
    initialize_agent_package,
)
from framework.graph import EdgeCondition, EdgeSpec, Goal, NodeSpec, SuccessCriterion
import framework.builder.package_generator as pg

# Create a minimal build session
session = BuildSession(name="richard_test2")
session.goal = Goal(
    id="goal_1",
    name="Test Goal",
    description="A simple test agent",
    success_criteria=[
        SuccessCriterion(id="sc_1", description="Completes successfully", metric="llm_judge", target="success")
    ],
    constraints=[],
)
session.nodes = [
    NodeSpec(
        id="start",
        name="Start Node",
        description="Entry point",
        node_type="event_loop",
        input_keys=[],
        output_keys=["result"],
        system_prompt="You are a helpful assistant.",
    ),
]
session.edges = []

# Set as active session (in-memory only, no disk persistence)
pg._session = session

# Now call initialize_agent_package
result = initialize_agent_package("richard_test2")
print(result)
