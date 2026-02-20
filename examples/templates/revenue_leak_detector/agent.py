"""Revenue Leak Detector Agent — LLM-driven event_loop nodes.

Graph topology
--------------
  monitor ──► analyze ──► notify ──► followup
                                           │
              ◄───────────────────────────┘  (loop while halt != true)

The agent runs until severity hits critical. Observed escalation:
  Cycle 1 → high     (GHOSTED Epsilon $18k + STALLED Gamma $25k → $43k at risk)
  Cycle 2 → critical ($62k at risk threshold crossed) → halt
"""

from framework.graph import EdgeSpec, EdgeCondition, Goal

from .config import default_config, metadata
from .nodes import monitor_node, analyze_node, notify_node, followup_node

# ---- Goal ----
goal = Goal(
    id="revenue-leak-detector",
    name="Revenue Leak Detector",
    description=(
        "Autonomous business health monitor that continuously scans the CRM pipeline, "
        "detects revenue leaks (ghosted prospects, stalled deals, overdue payments, "
        "churn risk), and sends structured alerts until a critical leak threshold "
        "triggers escalation."
    ),
)

# ---- Nodes ----
nodes = [monitor_node, analyze_node, notify_node, followup_node]

# ---- Edges ----
edges = [
    # monitor → analyze (always proceed to analysis after scanning)
    EdgeSpec(
        id="monitor-to-analyze",
        source="monitor",
        target="analyze",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # analyze → notify (always send alert after analysis)
    EdgeSpec(
        id="analyze-to-notify",
        source="analyze",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # notify → followup (always send follow-up emails after alerting)
    EdgeSpec(
        id="notify-to-followup",
        source="notify",
        target="followup",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # followup → monitor (loop back while not halted)
    EdgeSpec(
        id="followup-to-monitor",
        source="followup",
        target="monitor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='str(halt).lower() != "true"',
        priority=1,
    ),
]

entry_node = "monitor"
entry_points = {"start": "monitor"}
terminal_nodes = []
pause_nodes = []

__all__ = ["goal", "nodes", "edges"]
