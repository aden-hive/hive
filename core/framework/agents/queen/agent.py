"""Queen graph definition."""

from framework.graph import Goal
from framework.graph.edge import GraphSpec

from .nodes import queen_node

# ---------------------------------------------------------------------------
# Queen graph — the primary persistent conversation.
# Loaded by queen_orchestrator.create_queen(), NOT by AgentRunner.
# ---------------------------------------------------------------------------

queen_goal = Goal(
    id="queen-manager",
    name="Queen Manager",
    description=(
        "Manage the worker agent lifecycle and serve as the user's primary interactive interface."
    ),
    success_criteria=[],
    constraints=[],
)

queen_graph = GraphSpec(
    id="queen-graph",
    goal_id=queen_goal.id,
    version="1.0.0",
    entry_node="queen",
    entry_points={"start": "queen"},
    terminal_nodes=[],
    pause_nodes=[],
    nodes=[queen_node],
    edges=[],
    conversation_mode="continuous",
    loop_config={
        "max_iterations": 999_999,
        "max_tool_calls_per_turn": 30,
    },
)
