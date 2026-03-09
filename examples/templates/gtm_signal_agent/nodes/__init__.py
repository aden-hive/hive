"""Node definitions for GTM Signal Intelligence Agent."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="ICP Intake",
    description="Collect Ideal Customer Profile, target signals, and preferences.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[],
    output_keys=["icp_profile", "target_signals"],
    success_criteria="ICP and target signals are clearly defined and confirmed by the user.",
    system_prompt="""\
You are a GTM strategist. Ask the user to define their Ideal Customer Profile (ICP) 
and the types of buying signals they want to track (e.g., funding rounds, leadership changes).

**STEP 1 — Read and respond (text only, NO tool calls):**
Ask the user for their ICP and target signals if not provided. Confirm the details.

**STEP 2 — After the user confirms, call set_output:**
- set_output("icp_profile", "Detailed ICP description")
- set_output("target_signals", "List of target signals to monitor")
""",
    tools=[],
)

signal_scan_node = NodeSpec(
    id="signal_scan",
    name="Signal Scanning",
    description="Use Exa/news/web search to find buying signals from ICP-matched companies.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["icp_profile", "target_signals"],
    output_keys=["signal_candidates"],
    success_criteria="Identified at least one relevant buying signal.",
    system_prompt="""\
You are a signal researcher. Given an ICP profile and target signals, search for recent news.

Use the `exa_search` tool to find recent signals matching the target signals and ICP.

When done, call set_output:
- set_output("signal_candidates", "[List of companies and the signals found]")
""",
    tools=["exa_search"],
)

lead_enricher_node = NodeSpec(
    id="lead_enricher",
    name="Lead Enrichment",
    description="Find and enrich decision-makers via Apollo.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["signal_candidates"],
    output_keys=["enriched_leads"],
    success_criteria="Enriched leads with contact info.",
    system_prompt="""\
You are a data enrichment specialist. For the companies in `signal_candidates`, find decision makers.

Process them one-by-one to respect API rate limits. Use the `apollo_enrichment` tool to fetch contacts for the domains identified in the signals.

When done, call set_output:
- set_output("enriched_leads", "[List of leads with contact info and associated signals]")
""",
    tools=["apollo_enrichment"],
)

opportunity_scorer_node = NodeSpec(
    id="opportunity_scorer",
    name="Opportunity Scoring",
    description="Score each opportunity and route by score.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["enriched_leads"],
    output_keys=["opportunity_score", "score_band", "opportunity_data"],
    success_criteria="Assigned a score (0-100) and band (hot, warm, cold).",
    system_prompt="""\
You are a sales operations analyst. Score the enriched leads based on the strength of the signal and ICP fit.

Rubric:
- 80-100: Hot (Direct ICP match, clear buying signal like new funding)
- 50-79: Warm (Partial match or weaker signal)
- 0-49: Cold (Poor fit or no clear signal)

Pick the highest scoring lead to process next (in a full system, you would iterate).
Call set_output:
- set_output("opportunity_score", "<integer score>")
- set_output("score_band", "<hot, warm, or cold>")
- set_output("opportunity_data", "<JSON with lead and signal details>")
""",
    tools=[],
)

outreach_drafter_node = NodeSpec(
    id="outreach_drafter",
    name="Outreach Drafting",
    description="Draft short, signal-specific outreach emails.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["opportunity_data"],
    output_keys=["outreach_draft"],
    success_criteria="Drafted a personalized email.",
    system_prompt="""\
You are an expert SDR. Write a concise, personalized outreach email based on the `opportunity_data`.
Mention the specific signal (e.g., funding, hiring) in the first line. 
Keep it under 100 words.

Call set_output:
- set_output("outreach_draft", "<The email text>")
""",
    tools=[],
)

outreach_approval_node = NodeSpec(
    id="outreach_approval",
    name="Outreach Approval",
    description="Human-in-the-loop approval of drafts.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["outreach_draft", "opportunity_data"],
    output_keys=["approval_action", "approved_outreach"],
    success_criteria="User reviewed the draft and selected an action.",
    system_prompt="""\
Present the drafted outreach to the user for approval.

**STEP 1 — Present (text only, NO tool calls):**
Show the `opportunity_data` summary and the `outreach_draft`.
Ask: "Do you want to (1) Approve, (2) Edit, or (3) Skip this opportunity?"

**STEP 2 — After the user responds, call set_output:**
- If they approve:
  set_output("approval_action", "approve")
  set_output("approved_outreach", "<original draft>")
- If they edit:
  set_output("approval_action", "edit")
  set_output("approved_outreach", "<user's edited version>")
- If they skip:
  set_output("approval_action", "skip")
  set_output("approved_outreach", "")
""",
    tools=[],
)

hubspot_upsert_node = NodeSpec(
    id="hubspot_upsert",
    name="HubSpot Upsert",
    description="Create or update contacts/deals in CRM and optional tools.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["opportunity_data", "approval_action", "approved_outreach"],
    nullable_output_keys=["approved_outreach", "approval_action"],
    output_keys=["crm_status"],
    success_criteria="Upserted to CRM.",
    system_prompt="""\
You are an integration worker.
If the `approval_action` is "skip" or `score_band` was cold, just log the lead to the CRM as a skipped/nurture lead.
Otherwise, use `hubspot_upsert` to log the approved lead, and use `create_gmail_draft` with the `approved_outreach`.

Call set_output:
- set_output("crm_status", "Successfully synced to CRM and created drafts.")
""",
    tools=["hubspot_upsert", "create_gmail_draft", "send_slack_notification"],
)

weekly_digest_node = NodeSpec(
    id="weekly_digest",
    name="Weekly Digest",
    description="Client-facing digest of activity.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["crm_status"],
    output_keys=["last_digest_ts"],
    success_criteria="Presented summary to user.",
    system_prompt="""\
Present a brief summary of the completed cycle to the user.
"Here is the status of the latest run: <crm_status>. We've completed the cycle."
Ask the user if they want to run another scan now.

After they reply, call set_output:
- set_output("last_digest_ts", "<current_time_string>")
""",
    tools=[],
)

next_scan_gate_node = NodeSpec(
    id="next_scan_gate",
    name="Next Scan Gate",
    description="Prepare state for the next forever-alive cycle.",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=[],
    output_keys=["skip_to_next_scan"],
    success_criteria="Reset state.",
    system_prompt="""\
We are looping back to the beginning. 
Call set_output:
- set_output("skip_to_next_scan", "true")
""",
    tools=[],
)

__all__ = [
    "intake_node",
    "signal_scan_node",
    "lead_enricher_node",
    "opportunity_scorer_node",
    "outreach_drafter_node",
    "outreach_approval_node",
    "hubspot_upsert_node",
    "weekly_digest_node",
    "next_scan_gate_node",
]
