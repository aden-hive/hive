"""Node definitions for HubSpot Revenue Leak Detector Agent.

Data flow between nodes (via context memory):
  monitor  → sets: cycle, deals_scanned, overdue_invoices, support_escalations
             also stores deals in _deals_cache_var contextvar (session-isolated)
  analyze  → reads: cycle
             sets: cycle, leak_count, severity, total_at_risk, halt
             also stores leaks in _leaks_var contextvar
  notify   → reads: cycle, leak_count, severity, total_at_risk, halt
             sets: cycle, halt
  followup → reads: cycle, halt
             sets: cycle, halt
"""

from framework.graph import NodeSpec

monitor_node = NodeSpec(
    id="monitor",
    name="Monitor",
    description=(
        "Fetch all open HubSpot deals via MCP tools, assemble deal objects "
        "with days_inactive and contact email, then call scan_pipeline to store them."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle"],
    output_keys=["cycle", "deals_scanned", "overdue_invoices", "support_escalations"],
    tools=[
        "hubspot_search_deals",
        "hubspot_search_contacts",
        "scan_pipeline",
    ],
    system_prompt="""\
You are executing ONE HubSpot pipeline scan. Complete every step below in order.

CRITICAL RULE: You must NEVER invent, fabricate, or guess deal data.
If hubspot_search_deals returns an error, empty results, or you cannot call it,
you MUST call scan_pipeline with deals=[] and proceed. Do NOT create fictitious
contacts, companies, or deals under any circumstances.

STEP 1 — Fetch deals from HubSpot:
  Call hubspot_search_deals EXACTLY ONCE with:
    query: ""
    properties: ["dealname", "dealstage", "amount", "hs_lastmodifieddate"]
    limit: 50
  If the tool returns an error or empty results, skip to STEP 3 with deals=[].

STEP 2 — Build the deals array (only from real hubspot_search_deals results):
  For each result from the search:
  a. Skip any deal where dealstage is "closedwon" or "closedlost".
  b. Calculate days_inactive:
       Today's date minus the date in hs_lastmodifieddate (ISO 8601 format).
       If hs_lastmodifieddate is missing, use 0.
  c. Try to get the contact email:
       Call hubspot_search_contacts with query = the dealname and limit = 1.
       Use the first result's email property, or use "" if none found or if the tool errors.
       If hubspot_search_contacts fails for this deal, use email="" and continue to the next deal.
  d. Map dealstage to a readable name:
       "appointmentscheduled"  → "Demo Scheduled"
       "qualifiedtobuy"        → "Qualified"
       "presentationscheduled" → "Proposal Sent"
       "decisionmakerboughtin" → "Negotiation"
       "contractsent"          → "Contract Sent"
       Any other value          → use the raw dealstage value as-is.
  e. Add a deal object to the array:
       { "id": "<deal id>", "contact": "<dealname>", "email": "<contact email or empty>",
         "stage": "<readable stage>", "days_inactive": <int>, "value": <int amount> }

STEP 3 — Store results:
  Call scan_pipeline EXACTLY ONCE with:
    cycle: the 'cycle' value from current context
    deals: the deals array built in step 2 ([] if no open deals or on error)

STEP 4 — Set outputs:
  Call set_output for each key (all values as strings):
    "cycle"               → next_cycle returned by scan_pipeline
    "deals_scanned"       → deals_scanned returned by scan_pipeline
    "overdue_invoices"    → "0"
    "support_escalations" → "0"

Stop immediately after all set_output calls. Do NOT call scan_pipeline more than once.
""",
)

analyze_node = NodeSpec(
    id="analyze",
    name="Analyze",
    description=(
        "Detect GHOSTED (21+ days) and STALLED (10-20 days) revenue leak patterns "
        "from the deals stored by the monitor node."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle", "deals_scanned", "overdue_invoices", "support_escalations"],
    output_keys=["cycle", "leak_count", "severity", "total_at_risk", "halt"],
    tools=["detect_revenue_leaks"],
    system_prompt="""\
You are executing ONE revenue leak analysis step.

STEP 1 — Detect leaks:
  Call detect_revenue_leaks EXACTLY ONCE with:
    cycle: the 'cycle' value from context

STEP 2 — Set outputs (all values as strings):
  Call set_output for each key:
    "cycle"         → cycle value returned by detect_revenue_leaks
    "leak_count"    → leak_count returned by detect_revenue_leaks
    "severity"      → severity returned by detect_revenue_leaks
    "total_at_risk" → total_at_risk returned by detect_revenue_leaks
    "halt"          → halt returned by detect_revenue_leaks ("true" or "false")

Stop immediately after all set_output calls.
Do NOT call detect_revenue_leaks more than once.
Do NOT call hubspot tools or scan_pipeline.
""",
)

notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description=(
        "Build and send a formatted HTML revenue leak alert to Telegram, "
        "then pass halt state through to the followup node."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle", "leak_count", "severity", "total_at_risk", "halt"],
    output_keys=["cycle", "halt"],
    tools=["build_telegram_alert", "telegram_send_message"],
    system_prompt="""\
You are executing ONE revenue alert notification step.

STEP 1 — Build the alert:
  Call build_telegram_alert EXACTLY ONCE with:
    cycle:         'cycle' from context
    leak_count:    'leak_count' from context
    severity:      'severity' from context
    total_at_risk: 'total_at_risk' from context

STEP 2 — Send to Telegram:
  From the build_telegram_alert result, extract:
    html_message — the formatted HTML text
    chat_id      — the Telegram chat ID

  If chat_id is not empty:
    Call telegram_send_message EXACTLY ONCE with:
      chat_id:    the chat_id value above
      text:       the html_message value above
      parse_mode: "HTML"
    If telegram_send_message fails or returns an error, skip and continue to STEP 3.

  If chat_id is empty, skip telegram_send_message (credentials not configured).

STEP 3 — Set outputs (values as strings):
  Call set_output:
    "cycle" → 'cycle' from context (pass through unchanged)
    "halt"  → 'halt' from context (pass through as "true" or "false")

Stop immediately after all set_output calls.
Do NOT call build_telegram_alert more than once.
Do NOT call hubspot tools, scan_pipeline, or detect_revenue_leaks.
""",
)

followup_node = NodeSpec(
    id="followup",
    name="Followup",
    description=(
        "Send re-engagement emails to every GHOSTED contact this cycle "
        "using the send_email MCP tool, then pass halt state through."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle", "halt"],
    output_keys=["cycle", "halt"],
    tools=["prepare_followup_emails", "send_email"],
    system_prompt="""\
You are executing ONE follow-up email step.

STEP 1 — Prepare email payloads:
  Call prepare_followup_emails EXACTLY ONCE with:
    cycle: 'cycle' value from context

  The result contains a 'contacts' array. Each item has:
    contact  — recipient display name
    email    — recipient email address
    deal_id  — HubSpot deal ID
    subject  — email subject line
    html     — complete HTML email body

STEP 2 — Send emails:
  For each contact in contacts (if the array is not empty):
    Call send_email with:
      to:       contact.email
      subject:  contact.subject
      html:     contact.html
      provider: "resend"
    If send_email fails or returns an error for this contact, continue to the next contact.
    Do NOT retry a failed send.

  If no RESEND_API_KEY is configured, try provider: "gmail" instead.
  If the contacts array is empty, skip this step.

STEP 3 — Set outputs (values as strings):
  Call set_output:
    "cycle" → 'cycle' from context (pass through unchanged)
    "halt"  → 'halt' from context (pass through as "true" or "false")

Stop immediately after all set_output calls.
Do NOT call prepare_followup_emails more than once.
Do NOT call hubspot tools, scan_pipeline, detect_revenue_leaks, or build_telegram_alert.
""",
)

__all__ = [
    "monitor_node",
    "analyze_node",
    "notify_node",
    "followup_node",
]
