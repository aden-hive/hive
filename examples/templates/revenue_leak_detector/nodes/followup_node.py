from framework.graph import NodeSpec

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
