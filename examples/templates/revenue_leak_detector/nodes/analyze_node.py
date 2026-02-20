from framework.graph import NodeSpec

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
