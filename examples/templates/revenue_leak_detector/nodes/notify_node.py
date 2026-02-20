from framework.graph import NodeSpec

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
