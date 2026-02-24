"""Worker Health Judge — framework-level reusable monitoring graph.

Attaches to any worker agent runtime as a secondary graph. Fires on a
2-minute timer, reads the worker's session logs via ``get_worker_health_summary``,
accumulates observations in a continuous conversation context, and emits a
structured ``EscalationTicket`` when it detects a degradation pattern.

Usage::

    from framework.monitoring import judge_graph, judge_goal, HEALTH_JUDGE_ENTRY_POINT
    from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

    # Register tools bound to the worker runtime's event bus
    monitoring_registry = ToolRegistry()
    register_worker_monitoring_tools(
        monitoring_registry, worker_runtime._event_bus, storage_path
    )
    monitoring_tools = list(monitoring_registry.get_tools().values())
    monitoring_executor = monitoring_registry.get_executor()

    # Load judge as secondary graph on the worker runtime
    await worker_runtime.add_graph(
        graph_id="worker_health_judge",
        graph=judge_graph,
        goal=judge_goal,
        entry_points={"health_check": HEALTH_JUDGE_ENTRY_POINT},
        storage_subpath="graphs/worker_health_judge",
    )

Design:
- ``isolation_level="isolated"`` — the judge has its own memory, not
  polluting the worker's shared memory namespace.
- ``conversation_mode="continuous"`` — the judge's conversation carries
  across timer ticks. The conversation IS the judge's memory. It tracks
  trends by referring to its own prior messages ("Last check I saw 47
  steps; now 52; 5 new steps, 3 RETRY").
- No shared memory keys. No external state files.
"""

from __future__ import annotations

from framework.graph import Constraint, Goal, NodeSpec, SuccessCriterion
from framework.graph.edge import AsyncEntryPointSpec, GraphSpec

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

judge_goal = Goal(
    id="worker-health-monitor",
    name="Worker Health Monitor",
    description=(
        "Periodically assess the health of the worker agent by reading its "
        "execution logs. Detect degradation patterns (excessive retries, "
        "stalls, doom loops) and emit structured EscalationTickets when the "
        "worker needs attention."
    ),
    success_criteria=[
        SuccessCriterion(
            id="accurate-detection",
            description="Only escalates genuine degradation, not normal retry cycles",
            metric="false_positive_rate",
            target="low",
            weight=0.5,
        ),
        SuccessCriterion(
            id="timely-detection",
            description="Detects genuine stalls within 2 timer ticks (≤4 minutes)",
            metric="detection_latency_minutes",
            target="<=4",
            weight=0.5,
        ),
    ],
    constraints=[
        Constraint(
            id="conservative-escalation",
            description=(
                "Do not escalate on a single bad verdict or a brief stall. "
                "Require clear patterns (10+ consecutive bad verdicts or 4+ minute stall) "
                "before creating a ticket."
            ),
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="complete-ticket",
            description=(
                "Every EscalationTicket must have all required fields filled. "
                "Do not emit partial or placeholder tickets."
            ),
            constraint_type="hard",
            category="correctness",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

judge_node = NodeSpec(
    id="judge",
    name="Worker Health Judge",
    description=(
        "Autonomous health monitor for worker agents. Reads execution logs "
        "on each timer tick, compares to prior observations (via conversation "
        "history), and emits a structured EscalationTicket when a genuine "
        "degradation pattern is detected."
    ),
    node_type="event_loop",
    client_facing=False,   # Autonomous monitor, not interactive
    max_node_visits=0,     # Unbounded — runs on every timer tick
    input_keys=[],
    output_keys=["health_verdict"],
    nullable_output_keys=["health_verdict"],
    success_criteria=(
        "A clear health verdict is produced each check: either 'healthy' with "
        "a brief observation, or a complete EscalationTicket is emitted via "
        "emit_escalation_ticket and health_verdict describes the issue."
    ),
    tools=[
        "get_worker_health_summary",
        "emit_escalation_ticket",
    ],
    system_prompt="""\
You are the Worker Health Judge. You run every 2 minutes alongside a worker \
agent to monitor its execution health.

# Your Role

You observe the worker's iteration patterns over time and escalate only when \
you see genuine degradation — not normal retry cycles. Your conversation history \
IS your memory. On each check, refer to your previous observations to track trends.

# Check Procedure

On each timer tick (every 2 minutes):

## Step 1: Read health snapshot
Call get_worker_health_summary() with no arguments to auto-discover the active \
session. This returns:
- worker_agent_id: the worker's agent name — use this for ticket identity fields
- worker_graph_id: the worker's primary graph ID — use this for ticket identity fields
- session_id: the session being monitored — use this for worker_session_id in tickets
- total_steps: how many log steps have been recorded
- recent_verdicts: list of recent ACCEPT/RETRY/CONTINUE verdicts
- steps_since_last_accept: consecutive non-ACCEPT steps
- stall_minutes: wall-clock since last step (null if active)
- evidence_snippet: recent LLM output

## Step 2: Compare to prior check
Look at your conversation history. What was total_steps last time?
- If total_steps is UNCHANGED from prior check AND prior check was also unchanged:
  → STALL confirmed (worker has produced no new iterations in 4+ minutes).
  → Escalate with severity="high" or "critical" depending on stall duration.
- If total_steps increased: worker is making progress. Examine verdicts.

## Step 3: Analyze verdict pattern
- Healthy: Mix of ACCEPT and RETRY, steps_since_last_accept < 5. No action.
- Warning: steps_since_last_accept is 5-9. Note it, no escalation yet.
- Degraded: steps_since_last_accept >= 10. Examine evidence_snippet.
  - If evidence shows the agent is making real progress (complex reasoning,
    exploring solutions, productive tool use): may be a hard problem. Note it.
  - If evidence shows a loop (same error, same tool call, no new information):
    → Escalate with severity="medium" or "high".
- Critical: steps_since_last_accept >= 20, OR stall_minutes >= 4.
  → Escalate with severity="critical".

## Step 4: Decide

### If healthy:
set_output("health_verdict", "healthy: <brief observation>")
Done.

### If escalating:
Build an EscalationTicket JSON string with ALL required fields:
{
  "worker_agent_id": "<worker_agent_id from get_worker_health_summary>",
  "worker_session_id": "<session_id from get_worker_health_summary>",
  "worker_node_id": "<worker_graph_id from get_worker_health_summary>",
  "worker_graph_id": "<worker_graph_id from get_worker_health_summary>",
  "severity": "<low|medium|high|critical>",
  "cause": "<what you observed — concrete, specific>",
  "judge_reasoning": "<why you decided to escalate, not just dismiss>",
  "suggested_action": "<what you recommend: restart, human review, etc.>",
  "recent_verdicts": [<list from get_worker_health_summary>],
  "total_steps_checked": <int>,
  "steps_since_last_accept": <int>,
  "stall_minutes": <float or null>,
  "evidence_snippet": "<from get_worker_health_summary>"
}

Call: emit_escalation_ticket(ticket_json=<the JSON string above>)
Then: set_output("health_verdict", "escalated: <one-line summary>")

# Severity Guide

- low: Mild concern, worth noting. 5-9 consecutive bad verdicts.
- medium: Clear degradation pattern. 10-15 bad verdicts or brief stall (1-2 min).
- high: Serious issue. 15+ bad verdicts or stall 2-4 minutes or clear doom loop.
- critical: Worker is definitively stuck. 20+ bad verdicts or stall > 4 minutes.

# Conservative Bias

You MUST resist the urge to escalate prematurely. Worker agents naturally retry.
A node may legitimately need 5-8 retries before succeeding. Do not escalate unless:
1. The pattern is clear and sustained across your observation window, AND
2. The evidence shows no genuine progress

One missed escalation is less costly than two false alarms. The Queen will filter \
further. But do not be passive — genuine stalls and doom loops must be caught.

# Rules
- Never escalate on the FIRST check unless stall_minutes > 4
- Always call get_worker_health_summary FIRST before deciding anything
- All ticket fields are REQUIRED — do not submit partial tickets
- After any emit_escalation_ticket call, always set_output to complete the check
""",
)

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

HEALTH_JUDGE_ENTRY_POINT = AsyncEntryPointSpec(
    id="health_check",
    name="Worker Health Check",
    entry_node="judge",
    trigger_type="timer",
    trigger_config={
        "interval_minutes": 2,
        "run_immediately": True,  # Fire immediately to establish a baseline
    },
    isolation_level="isolated",  # Own memory namespace, not polluting worker's
)

# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

judge_graph = GraphSpec(
    id="worker-health-judge-graph",
    goal_id=judge_goal.id,
    version="1.0.0",
    entry_node="judge",
    entry_points={"health_check": "judge"},
    terminal_nodes=[],   # Forever-alive: fires on every timer tick
    pause_nodes=[],
    nodes=[judge_node],
    edges=[],
    conversation_mode="continuous",  # Conversation persists across timer ticks
    async_entry_points=[HEALTH_JUDGE_ENTRY_POINT],
    loop_config={
        "max_iterations": 10,          # One check shouldn't take many turns
        "max_tool_calls_per_turn": 3,  # get_summary + optionally emit_ticket
        "max_history_tokens": 16000,   # Compact — judge only needs recent context
    },
)
