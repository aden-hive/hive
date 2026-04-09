"""Queen agent definition.

The queen is a single AgentLoop — no orchestrator dependency.
Loaded by queen_orchestrator.create_queen().
"""

from framework.schemas.goal import Goal

from .nodes import queen_node

queen_goal = Goal(
    id="queen-manager",
    name="Queen Manager",
    description=(
        "Manage the worker agent lifecycle and serve as the user's primary interactive interface."
    ),
    success_criteria=[],
    constraints=[],
)

# Loop config -- used by queen_orchestrator to build LoopConfig
queen_loop_config = {
    "max_iterations": 999_999,
    "max_tool_calls_per_turn": 30,
    "max_context_tokens": 180_000,
}

__all__ = ["queen_goal", "queen_loop_config", "queen_node"]
