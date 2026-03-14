"""Node definitions for HubSpot Revenue Leak Detector Agent.

Data flow between nodes (via context/output keys):
  monitor  → sets: cycle, deals_scanned, overdue_invoices, support_escalations, deals_json
  analyze  → reads: cycle, deals_scanned, overdue_invoices, support_escalations, deals_json
             sets: cycle, leak_count, severity, total_at_risk, halt, leaks_json
  notify   → reads: cycle, leak_count, severity, total_at_risk, halt, leaks_json
             sets: cycle, halt
  followup → reads: cycle, halt, leaks_json
             sets: cycle, halt

deals_json and leaks_json are JSON strings serialised by scan_pipeline /
detect_revenue_leaks and passed explicitly through output_keys/input_keys so
state survives async event_loop node boundaries (contextvars do NOT persist
across nodes).
"""

from framework.graph import NodeSpec

monitor_node = NodeSpec(
    id="monitor",
    name="Monitor",
    description=(
        "Fetch all open HubSpot deals via MCP tools, resolve contact emails via "
        "deal associations, then call scan_pipeline to store and serialise them."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle"],
    output_keys=["cycle", "deals_scanned", "deals_json"],
    tools=[
        "hubspot_search_deals",
        "hubspot_get_deal",
        "hubspot_get_contact",
        "scan_pipeline",
    ],
    system_prompt="""\
You are executing ONE HubSpot pipeline scan. Complete every step below in order.

CRITICAL RULE: You must NEVER invent, fabricate, or guess deal data.
Do NOT create fictitious contacts, companies, or deals under any circumstances.

STEP 1 — Fetch ALL deals from HubSpot (paginate until done):
  Set accumulated_results = [] and after_cursor = "".
  Loop:
    Call hubspot_search_deals with:
      query: ""
      properties: ["dealname", "dealstage", "amount", "notes_last_contacted", "hs_lastmodifieddate"]
      limit: 100
      after: after_cursor   (use "" for the first call)
    If the response contains an "error" key and accumulated_results is empty:
      Wait 2 seconds and retry ONCE with the same parameters (after="" still).
      If the retry also fails, skip to STEP 3 with deals=[].
    Add the results from this response to accumulated_results.
    If the response contains paging.next.after, set after_cursor = that value and loop again.
    Otherwise (no paging.next.after), stop the loop.
    Use accumulated_results as the full list of deals for STEP 2.

STEP 2 — Build the deals array (only from real hubspot_search_deals results):
  For each result from the search:
  a. Skip any deal where dealstage is "closedwon" or "closedlost".
  b. Calculate days_inactive:
       Today's date minus notes_last_contacted (ISO 8601 format).
       notes_last_contacted reflects real sales activity (calls, emails, meetings logged in HubSpot).
       If notes_last_contacted is missing, fall back to hs_lastmodifieddate.
       If both are missing, use 0.
  c. Get the contact email via the Associations API (do NOT use hubspot_search_contacts):
       Call hubspot_get_deal with:
         deal_id: the deal's id
         properties: ["dealname"]
         include_associations: ["contacts"]
       From result.associations.contacts.results, take the first entry's id.
       If there are associated contacts:
         Call hubspot_get_contact with:
           contact_id: the first contact id
           properties: ["email", "firstname", "lastname"]
         Use the email property, or "" if the property is empty or missing.
       If there are no associations or the call errors, use email="".
       CRITICAL: ALWAYS add the deal even if email is empty — missing contact
       information does NOT invalidate the deal's revenue leak detection.
  d. Add a deal object to the array:
       { "id": "<deal id>", "contact": "<dealname>", "email": "<contact email or empty>",
         "stage": "<dealstage value>", "days_inactive": <int>, "value": <int amount>,
         "notes_last_contacted": "<raw notes_last_contacted value or empty string>",
         "hs_lastmodifieddate": "<raw hs_lastmodifieddate value or empty string>" }
       Always include the two raw date fields verbatim from HubSpot so that the pipeline
       scanner can recompute inactivity if needed.

STEP 3 — Store results:
  Call scan_pipeline EXACTLY ONCE with:
    cycle: the 'cycle' value from current context
    deals: the deals array built in step 2 ([] if no open deals or on error)

STEP 4 — Set outputs:
  Call set_output for each key (all values as strings):
    "cycle"         → next_cycle returned by scan_pipeline
    "deals_scanned" → deals_scanned returned by scan_pipeline
    "deals_json"    → deals_json returned by scan_pipeline (pass verbatim)

Stop immediately after all set_output calls. Do NOT call scan_pipeline more than once.
""",
)

analyze_node = NodeSpec(
    id="analyze",
    name="Analyze",
    description=(
        "Detect GHOSTED (30+ days) and STALLED (14-30 days) revenue leak patterns "
        "from deals passed via deals_json context key."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle", "deals_json"],
    output_keys=[
        "cycle",
        "leak_count",
        "severity",
        "total_at_risk",
        "halt",
        "leaks_json",
    ],
    tools=["detect_revenue_leaks"],
    system_prompt="""\
You are executing ONE revenue leak analysis step.

STEP 1 — Detect leaks:
  Call detect_revenue_leaks EXACTLY ONCE with:
    cycle:      the 'cycle' value from context
    deals_json: the 'deals_json' value from context (pass it through verbatim)

STEP 2 — Check for contradictions:
  If detect_revenue_leaks result contains a 'warning' key:
  This indicates a contradiction (deals exist but 0 leaks detected).
  DO NOT continue normally — this is a critical data inconsistency.
  Immediately halt the pipeline by setting:
    "severity" → "critical"
    "halt"     → "true"
  Log the contradiction message before halting.
  Do NOT proceed to STEP 3 if warning is present.

STEP 3 — Set outputs (all values as strings):
  Call set_output for each key:
    "cycle"         → cycle value returned by detect_revenue_leaks
    "leak_count"    → leak_count returned by detect_revenue_leaks
    "severity"      → severity returned by detect_revenue_leaks (use 'critical' if warning present)
    "total_at_risk" → total_at_risk returned by detect_revenue_leaks
    "halt"          → halt returned by detect_revenue_leaks ("true" or "false")
    "leaks_json"    → leaks_json returned by detect_revenue_leaks (pass verbatim)

Stop immediately after all set_output calls.
Do NOT call detect_revenue_leaks more than once.
Do NOT call hubspot tools or scan_pipeline.
""",
)

notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description=(
        "Build a formatted HTML revenue leak alert and send it to Telegram via MCP. "
        "Implements automatic chunking for messages exceeding Telegram's 4096 character limit. "
        "Then pass halt state through to the followup node."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=[
        "cycle",
        "leak_count",
        "severity",
        "total_at_risk",
        "halt",
        "leaks_json",
    ],
    output_keys=["cycle", "halt", "leaks_json"],
    tools=["build_telegram_alert", "telegram_get_chat_id", "telegram_send_message"],
    system_prompt="""\
You are executing ONE revenue alert notification step.

STEP 1 — Build the alert:
  Call build_telegram_alert EXACTLY ONCE with:
    cycle:         the 'cycle' value from context
    leak_count:    the 'leak_count' from context
    severity:      the 'severity' from context
    total_at_risk: the 'total_at_risk' from context
    leaks_json:    the 'leaks_json' from context (pass verbatim)

  The result contains 'html_message'.

STEP 2 — Get default chat ID:
  Call telegram_get_chat_id ONCE at the start to get the configured default chat ID.
  If the result contains an 'error', the agent should log the error
  and skip sending the Telegram message (but continue to STEP 3).
  If successful, use the 'chat_id' value for sending messages.
  The chat_id value is a string like "123456789" or "-1001234567890".

STEP 3 — Send the alert via Telegram MCP with chunking:
  Telegram message limit is 4096 characters. You MUST implement chunking:

  If len(html_message) <= 4096:
    Call telegram_send_message ONCE with:
      chat_id:    the 'chat_id' value from telegram_get_chat_id
      text:       the EXACT 'html_message' value (do NOT paraphrase or modify)
      parse_mode: "HTML"

  If len(html_message) > 4096:
    Split html_message into chunks of up to 4096 characters each.
    Split at NEWLINES (\\n) to keep content readable — try to keep lines intact.
    Call telegram_send_message ONCE for each chunk with:
      chat_id:    the 'chat_id' value from telegram_get_chat_id
      text:       the chunk (do NOT paraphrase or modify)
      parse_mode: "HTML"
    Stop sending if any chunk fails (returns an error).

STEP 4 — Set outputs (values as strings):
  Call set_output:
    "cycle"      → the 'cycle' from context (pass through unchanged)
    "halt"       → the 'halt' from context (pass through as "true" or "false")
    "leaks_json" → the 'leaks_json' from context (pass through verbatim)

Stop immediately after all set_output calls.
Do NOT call build_telegram_alert or telegram_get_chat_id more than once.
Do NOT call hubspot tools, scan_pipeline, detect_revenue_leaks, or prepare_followup_emails.

STEP 3 — Set outputs (values as strings):
  Call set_output:
    "cycle"      → the 'cycle' from context (pass through unchanged)
    "halt"       → the 'halt' from context (pass through as "true" or "false")
    "leaks_json" → the 'leaks_json' from context (pass through verbatim)

Stop immediately after all set_output calls.
Do NOT call build_telegram_alert more than once.
Do NOT call telegram_send_message more than necessary (once per chunk).
Do NOT call hubspot tools, scan_pipeline, or detect_revenue_leaks.
""",
)

followup_node = NodeSpec(
    id="followup",
    name="Followup",
    description=(
        "Create Gmail draft re-engagement emails for every GHOSTED contact this cycle "
        "using gmail_create_draft, then pass halt state through."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["cycle", "halt", "leaks_json"],
    output_keys=["cycle", "halt"],
    tools=["prepare_followup_emails", "gmail_create_draft"],
    system_prompt="""\
You are executing ONE follow-up email drafting step.

STEP 1 — Prepare email payloads:
  Call prepare_followup_emails EXACTLY ONCE with:
    cycle:      the 'cycle' value from context
    leaks_json: the 'leaks_json' value from context (pass it through verbatim)

  The result contains a 'contacts' array. Each item has:
    contact  — recipient display name
    email    — recipient email address
    deal_id  — HubSpot deal ID
    subject  — email subject line
    html     — complete HTML email body

STEP 2 — Create Gmail drafts:
  For each contact in contacts (if the array is not empty):
    Call gmail_create_draft with:
      to:      contact.email
      subject: contact.subject
      html:    contact.html
    If gmail_create_draft fails or returns an error for this contact,
    log the error and continue to the next contact.
    Do NOT retry a failed draft.

  If the contacts array is empty, skip this step.

STEP 3 — Set outputs (values as strings):
  Call set_output:
    "cycle" → the 'cycle' from context (pass through unchanged)
    "halt"  → the 'halt' from context (pass through as "true" or "false")

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
