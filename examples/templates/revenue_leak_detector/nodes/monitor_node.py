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
