"""Agent graph construction for Hive Coder."""

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec

from .nodes import coder_node, queen_node

# Goal definition
goal = Goal(
    id="agent-builder",
    name="Hive Agent Builder",
    description=(
        "Build complete, validated Hive agent packages from natural language "
        "specifications. Produces production-ready Python packages with goals, "
        "nodes, edges, system prompts, MCP configuration, and tests."
    ),
    success_criteria=[
        SuccessCriterion(
            id="valid-package",
            description="Generated agent package passes structural validation",
            metric="validation_pass",
            target="true",
            weight=0.30,
        ),
        SuccessCriterion(
            id="complete-files",
            description=(
                "All required files generated: agent.py, config.py, "
                "nodes/__init__.py, __init__.py, __main__.py, mcp_servers.json"
            ),
            metric="file_count",
            target=">=6",
            weight=0.25,
        ),
        SuccessCriterion(
            id="user-satisfaction",
            description="User reviews and approves the generated agent",
            metric="user_approval",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="framework-compliance",
            description=(
                "Generated code follows framework patterns: STEP 1/STEP 2 "
                "for client-facing and correct imports"
            ),
            metric="pattern_compliance",
            target="100%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="dynamic-tool-discovery",
            description=(
                "Always discover available tools dynamically via "
                "list_agent_tools before referencing tools in agent designs"
            ),
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="no-fabricated-tools",
            description="Only reference tools that exist in hive-tools MCP",
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="valid-python",
            description="All generated Python files must be syntactically correct",
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="self-verification",
            description="Run validation after writing code; fix errors before presenting",
            constraint_type="hard",
            category="quality",
        ),
    ],
)

# Nodes: primary coder node only.  The queen runs as an independent
# GraphExecutor with queen_node — not as part of this graph.
nodes = [coder_node]

# No edges needed — single event_loop node
edges = []

# Graph configuration
entry_node = "coder"
entry_points = {"start": "coder"}
pause_nodes = []
terminal_nodes = []  # Coder node has output_keys and can terminate

# No async entry points needed — the queen is now an independent executor,
# not a secondary graph receiving events via add_graph().
async_entry_points = []

# Module-level variables read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = (
    "You are Hive Coder, the best agent-building coding agent on the planet. "
    "You deeply understand the Hive agent framework at the source code level "
    "and produce production-ready agent packages from natural language. "
    "You can dynamically discover available framework tools, inspect runtime "
    "sessions and checkpoints from agents you build, and run their test suites. "
    "You follow coding agent discipline: read before writing, verify "
    "assumptions by reading actual code, adhere to project conventions, "
    "self-verify with validation, and fix your own errors. You are concise, "
    "direct, and technically rigorous. No emojis. No fluff."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


# ---------------------------------------------------------------------------
# Queen graph — runs as an independent persistent conversation in the TUI.
# Loaded by _load_judge_and_queen() in app.py, NOT by AgentRunner.
# ---------------------------------------------------------------------------

queen_goal = Goal(
    id="queen-manager",
    name="Queen Manager",
    description=(
        "Manage the worker agent lifecycle and serve as the user's primary "
        "interactive interface. Triage health escalations from the judge."
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
    terminal_nodes=["queen"],  # Queen node can terminate
    pause_nodes=[],
    nodes=[queen_node],
    edges=[],
    conversation_mode="continuous",
    loop_config={
        "max_iterations": 999_999,
        "max_tool_calls_per_turn": 30,
        "max_history_tokens": 32000,
    },
)
