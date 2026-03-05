"""Node definitions for Autonomous SRE Incident Resolution Agent."""

from framework.graph import NodeSpec

# Node 1: Alert Intake (client-facing)
alert_intake_node = NodeSpec(
    id="alert-intake",
    name="Alert Intake",
    description="Accept a production alert from the user and confirm incident details",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[],
    output_keys=["alert"],
    system_prompt="""\
You are the alert intake specialist for an autonomous SRE incident resolution agent.

**STEP 1 — Greet and collect alert (text only, NO tool calls):**
Ask the user to describe the production alert or paste the alert payload.

Clarify:
- Service name (e.g., payment-service, auth-api)
- Alert type (e.g., high error rate, latency spike, OOM, CPU overload)
- When it started
- Any initial observations

Keep it brief. One message, 3 questions max.

After your message, call ask_user() to wait for the user's response.

**STEP 2 — After the user responds, call set_output:**
- set_output("alert", "<JSON string: {service, alert_type, started_at, description}>")
""",
    tools=[],
)

# Node 2: Log Fetch (mock)
log_fetch_node = NodeSpec(
    id="log-fetch",
    name="Log Fetch",
    description="Fetch recent logs for the affected service using mock log retrieval",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["alert"],
    output_keys=["logs"],
    system_prompt="""\
You are a log retrieval specialist. Given an alert, fetch recent logs for the service.

Call fetch_mock_logs(service=<service_name>, alert_type=<alert_type>) to retrieve logs.

After the tool returns, store the result:
set_output("logs", "<JSON string of log entries returned by the tool>")
""",
    tools=["fetch_mock_logs"],
)

# Node 3: Incident Analyzer
incident_analyzer_node = NodeSpec(
    id="incident-analyzer",
    name="Incident Analyzer",
    description="Analyze logs to determine likely root cause and retrieve similar historical incidents",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["alert", "logs"],
    output_keys=["root_cause", "similar_incidents"],
    system_prompt="""\
You are an incident analysis specialist. Analyze the logs and alert to determine root cause.

**Step 1 — Analyze logs:**
Read the logs carefully. Identify:
- Error patterns (repeated exceptions, timeouts, OOM signals)
- Timing of first occurrence
- Affected components

**Step 2 — Retrieve similar historical incidents:**
Call get_similar_incidents(service=<service>, symptoms=<comma-separated key symptoms>) \
to find past incidents with similar patterns.

**Step 3 — Store outputs:**
set_output("root_cause", "<one clear sentence describing the most likely root cause>")
set_output("similar_incidents", "<JSON string of similar past incidents returned by tool, \
or '[]' if none found>")
""",
    tools=["get_similar_incidents"],
)

# Node 4: Severity + Confidence Estimator
severity_estimator_node = NodeSpec(
    id="severity-estimator",
    name="Severity & Confidence Estimator",
    description="Classify severity level and estimate confidence score for root cause accuracy",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["alert", "root_cause", "similar_incidents"],
    output_keys=["severity", "confidence"],
    system_prompt="""\
You are a severity and confidence estimation specialist.

**Classify severity** based on alert type and root cause:
- critical: data loss, full outage, security breach
- high: major feature broken, >50% error rate
- medium: degraded performance, partial failures
- low: minor issues, single user impact

**Estimate confidence (0-100)** based on:
- Log clarity: clear error messages → +30 points
- Pattern match: similar_incidents found with high similarity → +40 points
- Symptom specificity: specific vs vague symptoms → +30 points

If similar_incidents is empty or '[]', cap confidence at 70.

**Store outputs:**
set_output("severity", "<critical|high|medium|low>")
set_output("confidence", "<integer 0-100>")
""",
    tools=[],
)

# Node 5: Auto-Resolve
auto_resolve_node = NodeSpec(
    id="auto-resolve",
    name="Auto-Resolve",
    description="Suggest remediation steps, draft Slack update and Jira ticket when confidence >= 80 and severity != critical",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["alert", "root_cause", "severity", "confidence"],
    output_keys=["resolution_status"],
    system_prompt="""\
You are the auto-resolution specialist. Confidence is high enough to act autonomously.

**Step 1 — Draft Slack message:**
Call draft_slack_message(
    channel="#prod-alerts",
    service=<service>,
    root_cause=<root_cause>,
    severity=<severity>,
    remediation=<2-3 sentence remediation summary>
)

**Step 2 — Draft Jira ticket:**
Call draft_jira_ticket(
    service=<service>,
    root_cause=<root_cause>,
    severity=<severity>,
    steps=<numbered remediation steps as string>
)

**Step 3 — Present to user (text only, NO tool calls):**
Show:
- Root cause identified
- Severity level
- Confidence score
- Remediation steps (numbered list)
- Slack draft (from tool output)
- Jira ticket draft (from tool output)

Ask: "Shall I apply these remediation steps, or would you like to modify anything?"

After your message, call ask_user() to wait for the user's response.

**Step 4 — After user responds:**
set_output("resolution_status", "resolved" if user approves, else "modified")
""",
    tools=["draft_slack_message", "draft_jira_ticket"],
)

# Node 6: Escalate (HITL)
escalate_node = NodeSpec(
    id="escalate",
    name="Escalate to Human",
    description="Trigger human-in-the-loop escalation when confidence < 80 or severity is critical",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["alert", "root_cause", "severity", "confidence", "logs"],
    output_keys=["escalation_status"],
    system_prompt="""\
You are the escalation specialist. This incident requires human review.

**STEP 1 — Present investigation summary (text only, NO tool calls):**

Show the on-call engineer:
- **Alert**: service + alert type
- **Severity**: <severity> (CRITICAL if applicable — immediate action required)
- **Confidence**: <confidence>% — reason escalation was triggered
- **Root Cause Hypothesis**: <root_cause>
- **Key Log Evidence**: top 3 most relevant log lines
- **Similar Past Incidents**: list them if any, or "None found"
- **Recommended Investigation Steps**: 3-5 specific steps the engineer should take

Explain clearly why this was escalated (low confidence OR critical severity).

After your message, call ask_user() to wait for the engineer's response.

**STEP 2 — After engineer responds:**
- Acknowledge their decision
- If they provide a resolution: set_output("escalation_status", "resolved_by_human")
- If they need more info: answer their questions, call ask_user() again
- When done: set_output("escalation_status", "escalated_to_human")
""",
    tools=[],
)

# Node 7: Outcome Store
outcome_store_node = NodeSpec(
    id="outcome-store",
    name="Outcome Store",
    description="Store incident outcome in long-term memory and loop back for next alert",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["alert", "root_cause", "severity", "confidence", "resolution_status", "escalation_status"],
    output_keys=["stored"],
    system_prompt="""\
You are the outcome storage specialist. Store this incident for future learning.

**Step 1 — Store outcome:**
Call store_incident_outcome(
    service=<service from alert>,
    root_cause=<root_cause>,
    severity=<severity>,
    confidence=<confidence>,
    resolution=<resolution_status or escalation_status>,
    timestamp="now"
)

**Step 2 — Present summary to user (text only, NO tool calls):**
Show a brief incident summary:
- Service, severity, root cause
- How it was resolved (auto or human)
- Confidence score
- "Outcome stored for future learning."

Ask: "Would you like to handle another alert?"

After your message, call ask_user() to wait for the user's response.

**Step 3 — After user responds:**
set_output("stored", "true")
""",
    tools=["store_incident_outcome"],
)

__all__ = [
    "alert_intake_node",
    "log_fetch_node",
    "incident_analyzer_node",
    "severity_estimator_node",
    "auto_resolve_node",
    "escalate_node",
    "outcome_store_node",
]
