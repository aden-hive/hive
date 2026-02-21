"""Node definitions for Revenue Leak Detector Agent."""

from framework.graph import NodeSpec

monitor_node = NodeSpec(
    id="monitor",
    name="Monitor",
    description="Scan the CRM pipeline for the current cycle and collect raw signals.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["cycle"],
    output_keys=["cycle", "deals_scanned", "overdue_invoices", "support_escalations"],
    tools=["scan_pipeline"],
    system_prompt="""\
You are executing ONE pipeline scan step. Follow these steps in order:
1. Call scan_pipeline EXACTLY ONCE with the 'cycle' value from context (use 0 if missing).
2. Call set_output with key "cycle" and the returned next_cycle as a string.
3. Call set_output with key "deals_scanned" and the returned deals_scanned as a string.
4. Call set_output with key "overdue_invoices" and the returned overdue_invoices as a string.
5. Call set_output with key "support_escalations" and the returned support_escalations as a string.
Do NOT call scan_pipeline more than once. Stop immediately after step 5.
""",
)

analyze_node = NodeSpec(
    id="analyze",
    name="Analyze",
    description="Detect revenue leak patterns in the current pipeline snapshot.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["cycle", "deals_scanned", "overdue_invoices", "support_escalations"],
    output_keys=["cycle", "leak_count", "severity", "total_at_risk", "halt"],
    tools=["detect_revenue_leaks"],
    system_prompt="""\
You are executing ONE revenue leak analysis step. Follow these steps in order:
1. Call detect_revenue_leaks EXACTLY ONCE with the 'cycle' value from context. Do NOT call scan_pipeline.
2. Call set_output with key "cycle" and the returned cycle value as a string.
3. Call set_output with key "leak_count" and the returned leak_count as a string.
4. Call set_output with key "severity" and the returned severity as a string.
5. Call set_output with key "total_at_risk" and the returned total_at_risk as a string.
6. Call set_output with key "halt" and the returned halt as "true" or "false".
Do NOT call detect_revenue_leaks more than once. Do NOT call scan_pipeline. Stop immediately after step 6.
""",
)

notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description="Send a formatted revenue leak alert and pass halt state through.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["cycle", "leak_count", "severity", "total_at_risk", "halt"],
    output_keys=["cycle", "halt"],
    tools=["send_revenue_alert"],
    system_prompt="""\
You are executing ONE revenue alert notification step. Follow these steps in order:
1. Call send_revenue_alert EXACTLY ONCE with 'cycle', 'leak_count', 'severity', and 'total_at_risk' from context. Do NOT call scan_pipeline or detect_revenue_leaks.
2. Call set_output with key "cycle" passing through the same cycle value as a string.
3. Call set_output with key "halt" passing through the same halt value from context as "true" or "false".
Do NOT call send_revenue_alert more than once. Do NOT call scan_pipeline. Do NOT call detect_revenue_leaks. Stop immediately after step 3.
""",
)

followup_node = NodeSpec(
    id="followup",
    name="Followup",
    description="Send re-engagement emails to GHOSTED contacts and pass halt state through.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["cycle", "halt"],
    output_keys=["cycle", "halt"],
    tools=["send_followup_emails"],
    system_prompt="""\
You are executing ONE follow-up email step. Follow these steps in order:
1. Call send_followup_emails EXACTLY ONCE with the 'cycle' value from context.
2. Call set_output with key "cycle" passing through the same cycle value as a string.
3. Call set_output with key "halt" passing through the same halt value from context as "true" or "false".
Do NOT call scan_pipeline, detect_revenue_leaks, or send_revenue_alert. Stop immediately after step 3.
""",
)

__all__ = [
    "monitor_node",
    "analyze_node",
    "notify_node",
    "followup_node",
]
