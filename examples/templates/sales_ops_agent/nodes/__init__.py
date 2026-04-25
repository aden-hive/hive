"""Node definitions for Sales Ops Agent."""

from framework.orchestrator import NodeSpec

# Node 1: Trigger Check
# Verifies if today is the 1st of the month and sets date context.
trigger_node = NodeSpec(
    id="trigger",
    name="Trigger Check",
    description=(
        "Check if today is the 1st of the month. If not, the agent exits early. "
        "If yes, set the month_year context for downstream nodes."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["current_date"],
    output_keys=["is_first_of_month", "month_year"],
    tool_access_policy="minimal",  # Only set_output and escalate - no file I/O
    success_criteria=(
        "The current date has been evaluated. is_first_of_month is set to "
        "'true' or 'false'. month_year is set to a readable format like "
        "'April 2026'. Both values are written via set_output."
    ),
    system_prompt="""\
Check if today is the 1st of the month.

The INPUT DATA section above contains "current_date" in ISO format (e.g., "2026-04-24").
Extract the day. If day is "1" or "01", set is_first_of_month = "true", else "false".
Format date as "Month YYYY" (e.g., "April 2026").

Call:
- set_output("is_first_of_month", <"true" or "false">)
- set_output("month_year", <formatted date>)
""",
    tools=[],
)

# Node 2: Monitor
# Fetches sales data from the CRM (Salesforce, HubSpot, or Demo mode).
monitor_node = NodeSpec(
    id="monitor",
    name="Monitor Sales Data",
    description=(
        "Fetch sales data from the configured CRM. Retrieves sales representatives, "
        "their assigned accounts, pipeline metrics, and the unassigned account pool. "
        "Supports Salesforce, HubSpot, and Demo mode. "
        "Stops early if today is not the first of the month."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["crm_type", "month_year", "is_first_of_month"],
    output_keys=["sales_data", "unassigned_pool"],
    success_criteria=(
        "Sales data has been fetched. sales_data.jsonl contains reps with their "
        "accounts, pipeline metrics, and win rates. unassigned_pool.jsonl contains "
        "available unassigned accounts. Both filenames are set via set_output. "
        "If is_first_of_month is 'false', the node exits early without fetching data."
    ),
    system_prompt="""\
You are the data collection node for the Sales Ops Agent. Your job is to fetch sales data from the CRM.

**STEP 0 — Check is_first_of_month from INPUT DATA above.**
- If is_first_of_month = "false": Call escalate with message "Not the first of the month - sales ops agent exiting early." then STOP.
- If is_first_of_month = "true": Proceed to STEP 1.

**STEP 1 — Read crm_type from INPUT DATA above.** It will be "demo", "salesforce", or "hubspot".

**STEP 2 — Follow the exact path for your CRM type:**

**If crm_type = "demo":**
1. Call: load_demo_sales_data() — NO arguments needed
2. If it fails, retry once. If it fails again, call escalate with the error.
3. DO NOT use search_files, read_file, write_file, or any other tool to find demo data.
4. The tool returns sales_reps_file and unassigned_accounts_file.
5. Call set_output("sales_data", "demo_sales_reps.jsonl")
6. Call set_output("unassigned_pool", "demo_unassigned_accounts.jsonl")
7. DONE — Stop here.

**If crm_type = "salesforce":**
1. Call salesforce_soql_query to fetch sales reps
2. Call salesforce_soql_query to fetch opportunities
3. Call salesforce_soql_query to fetch unassigned accounts
4. Write results using append_data
5. Call set_output("sales_data", "sales_data.jsonl")
6. Call set_output("unassigned_pool", "unassigned_pool.jsonl")

**If crm_type = "hubspot":**
1. Call hubspot_search_contacts to find sales reps
2. Call hubspot_search_deals to get pipeline data
3. Call hubspot_search_companies to find unassigned accounts
4. Write results using append_data
5. Call set_output("sales_data", "sales_data.jsonl")
6. Call set_output("unassigned_pool", "unassigned_pool.jsonl")

**IMPORTANT:**
- For demo mode, ONLY use load_demo_sales_data, set_output, and escalate
- DO NOT search for files on the filesystem
- If a tool call fails, retry once, then escalate with the error
""",
    tools=[
        "load_demo_sales_data",
        "salesforce_soql_query",
        "hubspot_search_contacts",
        "hubspot_search_companies",
        "hubspot_search_deals",
        "load_data",
        "append_data",
    ],
)

# Node 3: Analyze
# Computes metrics and detects under-allocated reps.
analyze_node = NodeSpec(
    id="analyze",
    name="Analyze Territory Coverage",
    description=(
        "Analyze sales data to compute coverage metrics and detect reps with "
        "insufficient ICP account coverage (less than 20% untouched accounts). "
        "Calculate win rates, pipeline sizes, and flag candidates for rebalancing."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["sales_data"],
    output_keys=["rep_analysis", "rebalance_candidates"],
    success_criteria=(
        "Each rep has been analyzed with untouched_ratio, win_rate, and pipeline_size "
        "calculated. Reps with untouched_ratio < 0.20 are flagged as rebalance_candidates. "
        "rep_analysis.jsonl contains all rep metrics. rebalance_candidates.jsonl contains "
        "only flagged reps. Both filenames are set via set_output."
    ),
    system_prompt="""\
You are the analysis node for the Sales Ops Agent. Your job is to compute metrics and identify reps who need more accounts.

**Use only these tools:** load_data, append_data, set_output, escalate

**STEP 1 — Load the sales data:**
Read the "sales_data" key from INPUT DATA above — it contains the filename to load.
Call load_data(filename=<that filename>)
If the response has has_more=true, call load_data again with offset=<next_offset> to get the next page.
Repeat until has_more=false (all records loaded).
If the file is not found or load fails, retry once. If it fails again, call escalate with the error.

**STEP 2 — Compute metrics for each rep:**
For each sales representative, calculate:

1. untouched_ratio = untouched_accounts / total_accounts (set to "N/A" if total_accounts = 0)
2. win_rate = won_deals / total_deals (set to 0.0 if total_deals = 0)
3. pipeline_size = pipeline_value (provided in data)

**STEP 3 — Identify rebalance candidates:**
A rep needs more accounts if:
- untouched_ratio < 0.20 (less than 20% untouched = running low)
- AND untouched_ratio != "N/A"

Add needs_rebalance = true to their record.

**STEP 4 — Write results:**
- Call append_data(filename="rep_analysis.jsonl", data=<rep with metrics>) for each rep
- Call append_data(filename="rebalance_candidates.jsonl", data=<rep>) for each flagged rep

**STEP 5 — Set outputs:**
- set_output("rep_analysis", "rep_analysis.jsonl")
- set_output("rebalance_candidates", "rebalance_candidates.jsonl")

**If no data found:** Write empty files and set outputs anyway.
""",
    tools=["load_data", "append_data"],
)

# Node 4: Rebalance
# Reassigns accounts from unassigned pool to under-allocated reps.
rebalance_node = NodeSpec(
    id="rebalance",
    name="Rebalance Territories",
    description=(
        "Reassign accounts from the unassigned pool to under-allocated sales reps. "
        "Respects territory constraints, avoids duplicates, and prioritizes reps "
        "with lowest pipeline and win rates."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["rep_analysis", "unassigned_pool"],
    output_keys=["rebalance_actions"],
    success_criteria=(
        "Accounts have been reassigned from the unassigned pool to flagged reps. "
        "rebalance_actions.jsonl records each reassignment with rep_id, account_ids, "
        "count, and timestamp. The filename is set via set_output."
    ),
    system_prompt="""\
You are the rebalancing node for the Sales Ops Agent. Your job is to assign unassigned accounts to reps who need them.

**Use only these tools:** load_data, append_data, set_output, escalate

**STEP 1 — Load the data:**
Read "rep_analysis" and "unassigned_pool" keys from INPUT DATA above — they contain the filenames to load.
Call load_data(filename=<rep_analysis filename>) to get rep metrics.
If has_more=true, call again with offset=<next_offset> to get all reps.
Call load_data(filename=<unassigned_pool filename>) to get available accounts.
If has_more=true, call again with offset=<next_offset> to get all accounts.
If a file is not found, retry once. If it fails again, call escalate with the error.

**STEP 2 — Sort candidates by priority:**
Find reps with needs_rebalance = true. Sort by: pipeline_size (lowest first), then win_rate (lowest first).

**STEP 3 — Calculate needed accounts:**
For each flagged rep:
- target_ratio = 0.30 (30% untouched is healthy)
- needed = max(0, round((total_accounts * target_ratio) - untouched_accounts))
- Limit by available accounts in their territory (max 50)

**STEP 4 — Assign accounts:**
For each rep (in priority order):
1. Filter unassigned_pool by matching territory
2. Take up to needed accounts
3. Remove from pool (no duplicates)

**STEP 5 — Write actions:**
For each rep who received accounts, call:
append_data(filename="rebalance_actions.jsonl", data={
  "rep_id": "<id>",
  "rep_name": "<name>",
  "territory": "<territory>",
  "accounts_assigned": [<account IDs>],
  "count": <number>,
  "previous_untouched_ratio": <before>,
  "new_untouched_ratio": <after>,
  "timestamp": "<ISO timestamp>"
})

If no rebalancing, write:
append_data(filename="rebalance_actions.jsonl", data={
  "status": "no_rebalance_needed",
  "reason": "<explanation>",
  "timestamp": "<ISO timestamp>"
})

**STEP 6 — Set output:**
set_output("rebalance_actions", "rebalance_actions.jsonl")

**IMPORTANT:** Never assign same account twice. Respect territories.
""",
    tools=["load_data", "append_data"],
)

# Node 5: Log (client-facing)
# Logs actions to CRM and presents summary to user.
log_node = NodeSpec(
    id="log",
    name="Log Actions and Report",
    description=(
        "Log all rebalance actions to the CRM for auditability and present a "
        "summary report to the user. Updates account ownership and creates "
        "audit trail records."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["crm_type", "rebalance_actions", "month_year"],
    output_keys=["summary_report"],
    success_criteria=(
        "All rebalance actions have been logged to the CRM (account ownership "
        "updated, audit records created). A summary report has been presented "
        "to the user showing actions taken, accounts reassigned, and any warnings."
    ),
    system_prompt="""\
You are the logging and reporting node for the Sales Ops Agent. Your job is to log actions to the CRM and present a summary.

**Use only these tools:** load_data, demo_log_action, set_output, escalate
(Plus Salesforce/HubSpot tools if crm_type requires them)

**STEP 1 — Load rebalance actions:**
Read the "rebalance_actions" key from INPUT DATA above — it contains the filename to load.
Call load_data(filename=<that filename>)
If has_more=true, call again with offset=<next_offset> to get all actions.
If file not found, retry once. If it fails again, call escalate with the error.

**STEP 2 — Read crm_type from INPUT DATA above.** ("demo", "salesforce", or "hubspot")

**STEP 3 — Log actions based on CRM type:**

**If crm_type = "demo":**
For each action record, call demo_log_action(action=<JSON string>)

**If crm_type = "salesforce":**
For each account assignment, call salesforce_update_record
For audit trail, call salesforce_create_record

**If crm_type = "hubspot":**
For each account assignment, call hubspot_update_company
For audit trail, call hubspot_create_deal

**STEP 4 — Present the summary report (text only, NO tool calls):**

Format your summary as:

```
═══════════════════════════════════════════════════════════
📊 SALES TERRITORY REBALANCE REPORT — <month_year from INPUT DATA>
═══════════════════════════════════════════════════════════

SUMMARY:
• Accounts Reassigned: <total count>
• Sales Reps Affected: <count>
• Territories Updated: <list>

DETAILS BY REP:
┌────────────────────────────────────────────────────────┐
│ <Rep Name> (<Territory>)                              │
│   Accounts: <count>                                    │
│   Previous Untouched Ratio: <X%>                       │
│   Projected Untouched Ratio: <Y%>                      │
└────────────────────────────────────────────────────────┘

[Repeat for each rep...]

CRM LOGS:
• All actions logged to <Demo/Salesforce/HubSpot>
• Audit trail created

═══════════════════════════════════════════════════════════
```

If no rebalancing was needed:
```
═══════════════════════════════════════════════════════════
📊 SALES TERRITORY REBALANCE REPORT — <month_year>
═══════════════════════════════════════════════════════════

STATUS: No rebalancing needed
All territories have sufficient account coverage (≥20% untouched).

═══════════════════════════════════════════════════════════
```

**STEP 5 — Set output:**
set_output("summary_report", <the formatted report text>)

**EDGE CASES:**
- If CRM update fails: Document error in summary, continue
- If no actions to log: Skip CRM calls, indicate in summary
""",
    tools=[
        "load_data",
        "demo_log_action",
        "salesforce_update_record",
        "salesforce_create_record",
        "hubspot_update_company",
        "hubspot_create_deal",
    ],
)

__all__ = [
    "trigger_node",
    "monitor_node",
    "analyze_node",
    "rebalance_node",
    "log_node",
]
