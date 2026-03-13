"""Node definitions for Churn Risk Agent."""

from framework.graph import NodeSpec

# Node 1: Signal Intake
signal_intake_node = NodeSpec(
    id="signal_intake",
    name="Signal Intake",
    description="Process customer account data",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["account_data"],
    output_keys=["confirmed_account_data"],
    nullable_output_keys=[],
    success_criteria="confirmed_account_data has been set with the account data.",
    system_prompt="""\
You are a data processor. Account data has been provided in account_data.

IMMEDIATELY call set_output — do NOT ask questions, do NOT wait:
set_output("confirmed_account_data", "py the exact account_data value here>")
""",
    tools=[],
)

# Node 2: Risk Scoring
risk_scoring_node = NodeSpec(
    id="risk_scoring",
    name="Risk Scoring",
    description="Score churn risk based on account signals",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["confirmed_account_data"],
    output_keys=["risk_level", "risk_score", "risk_reasoning"],
    nullable_output_keys=[],
    success_criteria="risk_level, risk_score, and risk_reasoning have all been set.",
    system_prompt="""\
You are a churn risk scorer. Score the account immediately.

Scoring rules (add points for each that applies):
- Last login > 30 days ago: +30
- Last login 15-30 days ago: +15
- Feature usage monthly or never: +20
- Support tickets >= 3 in last 30 days: +20
- NPS score <= 6: +20
- Contract renewal < 30 days away: +10

Risk levels: HIGH >= 60, MEDIUM 30-59, LOW < 30

Compute the score from the account data, then call set_output three times:
set_output("risk_score", "<number>")
set_output("risk_level", "<HIGH or MEDIUM or LOW>")
set_output("risk_reasoning", "<bullet list of criteria applied and points>")
""",
    tools=[],
)

# Node 3: Routing
routing_node = NodeSpec(
    id="routing",
    name="Routing Decision",
    description="Route based on risk level",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["risk_level", "risk_score", "risk_reasoning", "confirmed_account_data"],
    output_keys=["routing_decision"],
    nullable_output_keys=[],
    success_criteria="routing_decision has been set.",
    system_prompt="""\
Look at risk_level and IMMEDIATELY call set_output:

If risk_level is HIGH: set_output("routing_decision", "escalate")
If risk_level is MEDIUM: set_output("routing_decision", "outreach")
If risk_level is LOW: set_output("routing_decision", "monitor")

Call set_output now. No explanation needed.
""",
    tools=[],
)

# Node 4: Escalation — HIGH risk
escalation_node = NodeSpec(
    id="escalation",
    name="Escalation Alert",
    description="Alert CSM for HIGH risk accounts",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["confirmed_account_data", "risk_score", "risk_reasoning"],
    output_keys=["escalation_status"],
    nullable_output_keys=["escalation_status"],
    success_criteria="Escalation alert presented and escalation_status set.",
    system_prompt="""\
Present this escalation alert to the CSM, then call set_output.

🚨 HIGH CHURN RISK ALERT
Account: [from confirmed_account_data]
Risk Score: [risk_score]/100
Reasoning: [risk_reasoning]

Recommended action:
- Schedule emergency call if renewal < 14 days
- Send check-in within 24 hours if usage dropped
- Loop in support lead if tickets are high

Then IMMEDIATELY call:
set_output("escalation_status", "acknowledged")
""",
    tools=[],
)

# Node 5: Outreach Draft — MEDIUM risk
outreach_node = NodeSpec(
    id="outreach",
    name="Outreach Draft",
    description="Draft re-engagement email for CSM approval",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["confirmed_account_data", "risk_score", "risk_reasoning"],
    output_keys=["outreach_approved", "outreach_draft"],
    nullable_output_keys=["outreach_approved", "outreach_draft"],
    success_criteria="outreach_approved and outreach_draft have been set.",
    system_prompt="""\
Draft a re-engagement email and ask the CSM to approve it.

Present:
📧 DRAFT EMAIL — approve, edit, or reject?
To: [customer from confirmed_account_data]
Subject: Checking in — how can we help?

[Write a 3-paragraph personalised email based on their usage signals]

Risk context: [risk_reasoning]

After CSM responds:
If approved: set_output("outreach_approved", "true") then set_output("outreach_draft", "<email text>")
If rejected: set_output("outreach_approved", "false") then set_output("outreach_draft", "REJECTED")
""",
    tools=[],
)

# Node 6: Monitor — LOW risk
monitor_node = NodeSpec(
    id="monitor",
    name="Monitor",
    description="Log low risk account",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["confirmed_account_data", "risk_score", "risk_reasoning"],
    output_keys=["monitor_status"],
    nullable_output_keys=["monitor_status"],
    success_criteria="monitor_status has been set.",
    system_prompt="""\
IMMEDIATELY call set_output:
set_output("monitor_status", "low_risk_logged — re-check in 7 days")
""",
    tools=[],
)

# Node 7: Output Log
output_node = NodeSpec(
    id="output",
    name="Output Log",
    description="Present audit trail",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[
        "confirmed_account_data",
        "risk_level",
        "risk_score",
        "risk_reasoning",
        "routing_decision",
    ],
    output_keys=["audit_log"],
    nullable_output_keys=[
        "escalation_status",
        "outreach_approved",
        "outreach_draft",
        "monitor_status",
    ],
    success_criteria="audit_log has been set.",
    system_prompt="""\
Present the final assessment summary and call set_output.

✅ CHURN RISK ASSESSMENT COMPLETE
Account: [confirmed_account_data]
Risk Level: [risk_level] ([risk_score]/100)
Action: [routing_decision]
Reasoning: [risk_reasoning]

Then IMMEDIATELY call:
set_output("audit_log", "account=[confirmed_account_data] risk=[risk_level] score=[risk_score] action=[routing_decision]")
""",
    tools=[],
)


__all__ = [
    "signal_intake_node",
    "risk_scoring_node",
    "routing_node",
    "escalation_node",
    "outreach_node",
    "monitor_node",
    "output_node",
]
