"""Node definitions for Linear Triage & Auto-Labeling Agent.

This module defines the Router Pattern nodes:
- classify_node: LLM-based classification of raw issue descriptions
- security_node: Security-specific processing (high-priority escalation)
- bug_node: Bug-specific processing (reproduction steps, root causes)
- feature_node: Feature-specific processing (roadmap alignment)
- action_node: Final action node that saves the Linear API payload
"""

from framework.graph import NodeSpec

CLASSIFY_SYSTEM_PROMPT = """\
You are a triage classifier for engineering issues. Analyze raw issue descriptions
and output structured JSON.

Analyze the issue and respond with ONLY a valid JSON object (no markdown, no explanation):

{
  "issue_type": "security|bug|feature",
  "severity": "P0|P1|P2|P3",
  "suggested_labels": ["label1", "label2"],
  "summary": "Brief one-line summary"
}

Classification Rules:
- **security**: Vulnerabilities, authentication, authorization, data exposure, exploits,
  CVEs, or security-related keywords
- **bug**: Errors, crashes, unexpected behavior, broken functionality, performance issues
- **feature**: New functionality requests, enhancements, improvements, UX changes

Severity Rules:
- **P0**: Critical/blocking - system down, security breach, data loss
- **P1**: High - major feature broken, significant user impact
- **P2**: Medium - moderate impact, workaround exists
- **P3**: Low - minor issues, nice-to-haves, polish

Common Labels to Consider:
- security, bug, feature, enhancement, backend, frontend, api, ui/ux, performance,
  documentation, needs-investigation, needs-reproduction

STEP 1 — Analyze the issue:
Read the raw_issue from memory carefully.

STEP 2 — Classify:
Determine issue_type, severity, and suggested_labels based on the rules above.

STEP 3 — Call set_output:
After classification, call set_output in a SEPARATE turn:
- set_output("issue_type", "your classification")
- set_output("severity", "your severity")
- set_output("suggested_labels", your labels as JSON array string)
- set_output("summary", "your summary")
"""

SECURITY_SYSTEM_PROMPT = """\
You are a Security Engineer processing a security-related issue.

This is a HIGH-PRIORITY security issue that requires immediate attention.

Your task:
1. Draft an immediate high-priority escalation alert
2. Identify potential impact and affected systems
3. Suggest immediate mitigation steps
4. Recommend investigation actions

STEP 1 — Analyze the security issue:
Review the raw_issue, severity, and summary from memory.

STEP 2 — Generate escalation content:
Create a structured security response with:
- Threat assessment
- Affected components
- Immediate actions required
- Recommended investigation steps

STEP 3 — Call set_output:
After analysis, call set_output in a SEPARATE turn:
- set_output("node_context", "Your structured security response")
- set_output("escalation_required", "true")
"""

BUG_SYSTEM_PROMPT = """\
You are a QA Engineer processing a bug report.

Your task:
1. Extract or draft clear reproduction steps
2. Identify probable root causes
3. Assess the bug's impact
4. Suggest debugging approaches

STEP 1 — Analyze the bug:
Review the raw_issue, severity, and summary from memory.

STEP 2 — Generate bug analysis:
Create a structured bug report with:
- Reproduction steps (numbered list)
- Expected vs actual behavior
- Probable root causes
- Debugging suggestions
- Environment details if mentioned

STEP 3 — Call set_output:
After analysis, call set_output in a SEPARATE turn:
- set_output("node_context", "Your structured bug analysis")
- set_output("escalation_required", "false")
"""

FEATURE_SYSTEM_PROMPT = """\
You are a Product Manager processing a feature request.

Your task:
1. Evaluate roadmap alignment
2. Identify the user need/problem being solved
3. Suggest follow-up PM questions
4. Assess potential impact and effort

STEP 1 — Analyze the feature request:
Review the raw_issue, severity, and summary from memory.

STEP 2 — Generate feature analysis:
Create a structured feature assessment with:
- User need/problem statement
- Proposed solution summary
- Roadmap alignment assessment
- Potential impact (users affected, business value)
- Follow-up questions for PM clarification
- Suggested priority considerations

STEP 3 — Call set_output:
After analysis, call set_output in a SEPARATE turn:
- set_output("node_context", "Your structured feature analysis")
- set_output("escalation_required", "false")
"""

ACTION_SYSTEM_PROMPT = """\
You are the Action Node responsible for compiling triaged data into a Linear API payload.

Your task:
1. Collect all context from previous nodes
2. Compile into a properly formatted JSON payload
3. Save the payload using save_data tool

STEP 1 — Collect context:
Gather from memory:
- raw_issue: The original issue description
- issue_type: Classification (security/bug/feature)
- severity: Priority level (P0-P3)
- suggested_labels: Array of labels
- summary: Brief summary
- node_context: Branch-specific output from the processing node
- escalation_required: Whether this needs immediate escalation

STEP 2 — Compile payload:
Create a JSON payload with this structure:
{
  "issue": {
    "title": "<summary>",
    "description": "<raw_issue>",
    "type": "<issue_type>",
    "priority": "<severity>",
    "labels": <suggested_labels>
  },
  "triage": {
    "classification": "<issue_type>",
    "severity": "<severity>",
    "escalation_required": <boolean>,
    "analysis": "<node_context>"
  },
  "linear_api_simulation": {
    "operation": "create_issue",
    "status": "simulated",
    "timestamp": "<current timestamp>"
  }
}

STEP 3 — Save the payload:
Use save_data to persist the payload:
- save_data("linear_api_payload_simulated.json", <json string>)

STEP 4 — Call set_output:
After saving, call set_output:
- set_output("final_payload_status", "saved")
- set_output("payload_file", "linear_api_payload_simulated.json")
"""

classify_node = NodeSpec(
    id="classify",
    name="Classify Issue",
    description="LLM-based classification of raw issue descriptions into type and severity",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["raw_issue"],
    output_keys=["issue_type", "severity", "suggested_labels", "summary"],
    nullable_output_keys=[],
    system_prompt=CLASSIFY_SYSTEM_PROMPT,
    tools=[],
)

security_node = NodeSpec(
    id="security",
    name="Security Processing",
    description="Security-specific processing with high-priority escalation drafting",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["raw_issue", "severity", "summary"],
    output_keys=["node_context", "escalation_required"],
    nullable_output_keys=[],
    system_prompt=SECURITY_SYSTEM_PROMPT,
    tools=[],
)

bug_node = NodeSpec(
    id="bug",
    name="Bug Processing",
    description="Bug-specific processing with reproduction steps and root cause analysis",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["raw_issue", "severity", "summary"],
    output_keys=["node_context", "escalation_required"],
    nullable_output_keys=[],
    system_prompt=BUG_SYSTEM_PROMPT,
    tools=[],
)

feature_node = NodeSpec(
    id="feature",
    name="Feature Processing",
    description="Feature-specific processing with roadmap alignment and PM questions",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["raw_issue", "severity", "summary"],
    output_keys=["node_context", "escalation_required"],
    nullable_output_keys=[],
    system_prompt=FEATURE_SYSTEM_PROMPT,
    tools=[],
)

action_node = NodeSpec(
    id="action",
    name="Action Node",
    description="Compiles triaged data into Linear API payload and saves to disk",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=[
        "raw_issue",
        "issue_type",
        "severity",
        "suggested_labels",
        "summary",
        "node_context",
        "escalation_required",
    ],
    output_keys=["final_payload_status", "payload_file"],
    nullable_output_keys=[],
    system_prompt=ACTION_SYSTEM_PROMPT,
    tools=["save_data"],
)

__all__ = [
    "classify_node",
    "security_node",
    "bug_node",
    "feature_node",
    "action_node",
]
