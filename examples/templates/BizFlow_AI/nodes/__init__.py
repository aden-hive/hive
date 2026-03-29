"""Node definitions for BizFlow AI - Multi-pipeline business automation."""

from framework.graph import NodeSpec

# Node 1: Parse requirements
parse_node = NodeSpec(
    id="parse-requirements",
    name="Parse Requirements",
    description="Parse natural language requirements into structured pipeline specifications.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["requirements"],
    output_keys=["parsed_requirements"],
    system_prompt="""\
You are an expert n8n workflow architect.

Parse the user's requirements into a structured JSON format with:
- pipelines: array of pipeline specifications
- triggers: all required trigger types
- actions: all required action types
- integrations: all external services needed

Return a JSON object with these fields.
""",
    tools=[],
)

# Node 2: Generate CV Screening Pipeline
cv_pipeline_node = NodeSpec(
    id="generate-cv-pipeline",
    name="Generate CV Screening Pipeline",
    description="Generate n8n workflow JSON for CV screening pipeline.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["parsed_requirements"],
    output_keys=["pipeline_cv_screening"],
    system_prompt="""\
You are an n8n workflow expert.

Generate a CV screening pipeline with:
- Webhook and Google Drive triggers
- OpenAI CV analysis
- Email notifications
- Calendar scheduling
- CRM integration

Return a complete n8n workflow JSON object.
""",
    tools=[],
)

# Node 3: Generate Signal Engine Pipeline
signal_pipeline_node = NodeSpec(
    id="generate-signal-pipeline",
    name="Generate Signal Engine Pipeline",
    description="Generate n8n workflow JSON for signal decision engine.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["parsed_requirements"],
    output_keys=["pipeline_signal_engine"],
    system_prompt="""\
You are an n8n workflow expert.

Generate a signal decision engine with:
- Webhook trigger
- OpenAI signal analysis
- Slack notifications
- CRM task creation
- Email escalations

Return a complete n8n workflow JSON object.
""",
    tools=[],
)

# Node 4: Generate Revenue Monitor Pipeline
revenue_pipeline_node = NodeSpec(
    id="generate-revenue-pipeline",
    name="Generate Revenue Monitor Pipeline",
    description="Generate n8n workflow JSON for revenue leak detector.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["parsed_requirements"],
    output_keys=["pipeline_revenue_monitor"],
    system_prompt="""\
You are an n8n workflow expert.

Generate a revenue leak detector with:
- Schedule and webhook triggers
- Stripe integration
- OpenAI revenue analysis
- Slack finance notifications
- Email retention campaigns

Return a complete n8n workflow JSON object.
""",
    tools=[],
)

# Node 5: Generate Contract Watchdog Pipeline
contract_pipeline_node = NodeSpec(
    id="generate-contract-pipeline",
    name="Generate Contract Watchdog Pipeline",
    description="Generate n8n workflow JSON for contract compliance monitor.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["parsed_requirements"],
    output_keys=["pipeline_contract_watchdog"],
    system_prompt="""\
You are an n8n workflow expert.

Generate a contract compliance monitor with:
- Schedule and manual triggers
- Google Drive document access
- OpenAI contract analysis
- Jira task creation
- Slack alerts

Return a complete n8n workflow JSON object.
""",
    tools=[],
)

# Node 6: Generate HR Monitor Pipeline
hr_pipeline_node = NodeSpec(
    id="generate-hr-pipeline",
    name="Generate HR Monitor Pipeline",
    description="Generate n8n workflow JSON for HR risk monitor.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["parsed_requirements"],
    output_keys=["pipeline_hr_monitor"],
    system_prompt="""\
You are an n8n workflow expert.

Generate an HR risk monitor with:
- Schedule and webhook triggers
- HR system integration
- OpenAI HR analytics
- Slack HR alerts
- Calendar scheduling

Return a complete n8n workflow JSON object.
""",
    tools=[],
)

# Node 7: Merge Workflows
merge_node = NodeSpec(
    id="merge-workflows",
    name="Merge Workflows",
    description="Merge individual pipeline workflows into a single workflow.",
    node_type="event_loop",
    client_facing=False,
    input_keys=[
        "pipeline_cv_screening",
        "pipeline_signal_engine",
        "pipeline_revenue_monitor",
        "pipeline_contract_watchdog",
        "pipeline_hr_monitor"
    ],
    output_keys=["merged_workflow"],
    system_prompt="""\
You are an n8n workflow integrator.

Merge the individual pipeline workflows into a single comprehensive n8n workflow.
Add placeholder values for all credentials and configuration.

Return a JSON object with:
- name: "Multi-Pipeline Business Automation"
- nodes: array of all nodes with adjusted positions
- connections: all workflow connections
- placeholder_values: object with all required credentials
""",
    tools=[],
)

# Node 8: Validate Workflow
validate_node = NodeSpec(
    id="validate-workflow",
    name="Validate Workflow",
    description="Validate the generated n8n workflow.",
    node_type="event_loop",
    client_facing=True,  # Show results to user
    input_keys=["merged_workflow"],
    output_keys=["validation_results", "final_workflow"],
    system_prompt="""\
You are an n8n workflow validator.

Validate the merged workflow and present it to the user.
Check for:
- Missing nodes
- Proper connections
- Placeholder values
- Potential errors

Present the validation results and ask if the user wants to:
1. Approve the workflow
2. Request revisions
3. Save to file

If approved, set output with the final workflow.
""",
    tools=["save_data"],
)

__all__ = [
    "parse_node",
    "cv_pipeline_node",
    "signal_pipeline_node",
    "revenue_pipeline_node",
    "contract_pipeline_node",
    "hr_pipeline_node",
    "merge_node",
    "validate_node",
]