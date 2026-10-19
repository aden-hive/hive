"""Queen agent definition.

The queen is a single AgentLoop — no orchestrator dependency.
Loaded by queen_orchestrator.create_queen().
"""

from framework.schemas.goal import Goal

from .nodes import queen_node

queen_goal = Goal(
    id="queen-manager",
    name="Queen Manager",
    description=("Manage the worker agent lifecycle and serve as the user's primary interactive interface."),
    success_criteria=[],
    constraints=[],
)

# Loop config -- used by queen_orchestrator to build LoopConfig
queen_loop_config = {
    "max_iterations": 999_999,
    # Budget 30 -> soft checkpoint reminders at 30/60/90/120; hard stop
    # at budget * tool_call_hard_multiple (default 5) = 150.
    "tool_call_budget": 30,
    "max_context_tokens": 180_000,
}

# Colony queen runs longer-horizon orchestration than an independent queen, so
# it gets a wider tool-call envelope: budget 50 * hard_multiple 10 = hard stop
# at 500. Selected by queen_orchestrator when effective_phase == "colony".
queen_colony_loop_config = {
    "max_iterations": 999_999,
    "tool_call_budget": 50,
    "tool_call_hard_multiple": 10,
    "max_context_tokens": 180_000,
}

__all__ = ["queen_goal", "queen_loop_config", "queen_colony_loop_config", "queen_node"]
