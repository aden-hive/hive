"""Node definitions for Inbox Management Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Receives user rules and max_emails, confirms understanding with user.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description=(
        "Receive and validate input parameters: rules and max_emails. "
        "Present the interpreted rules back to the user for confirmation."
    ),
    node_type="event_loop",
    client_facing=True,
    input_keys=["rules", "max_emails"],
    output_keys=["rules", "max_emails"],
    system_prompt="""\
You are an inbox management assistant. The user has provided rules for managing their emails.

**STEP 1 — Respond to the user (text only, NO tool calls):**

Read the user's rules from the input context. Present a clear summary of what you will do with their emails based on their rules.

The following Gmail actions are available — map the user's rules to whichever apply:
- **Trash** emails
- **Mark as spam**
- **Mark as important** / unmark important
- **Mark as read** / mark as unread
- **Star** / unstar emails
- **Add/remove Gmail labels** (INBOX, UNREAD, IMPORTANT, STARRED, SPAM, CATEGORY_PERSONAL, CATEGORY_SOCIAL, CATEGORY_PROMOTIONS, CATEGORY_UPDATES, CATEGORY_FORUMS)

Present the rules back to the user in plain language. Do NOT refuse rules — if the user asks for any of the above actions, confirm you will do it.

Also confirm the batch size (max_emails). If max_emails is not provided, default to 100.

Ask the user to confirm: "Does this look right? I'll proceed once you confirm."

**STEP 2 — After the user confirms, call set_output:**

- set_output("rules", <the confirmed rules as a clear text description>)
- set_output("max_emails", <the confirmed max_emails as a string number, e.g. "100">)
""",
    tools=[],
)

# Node 2: Fetch Emails (event_loop — calls bulk_fetch_emails tool)
# Fetches emails from Gmail inbox via the bulk_fetch_emails custom script tool.
fetch_emails_node = NodeSpec(
    id="fetch-emails",
    name="Fetch Emails",
    description=(
        "Fetch emails from the Gmail inbox up to the configured batch limit. "
        "Calls bulk_fetch_emails tool, which fetches via Gmail API and writes "
        "compact JSONL to session data_dir."
    ),
    node_type="event_loop",
    client_facing=False,
    input_keys=["rules", "max_emails"],
    output_keys=["emails"],
    system_prompt="""\
You are a data pipeline step. Your ONLY job is to fetch emails from Gmail by calling the bulk_fetch_emails tool.

**Execute these exact steps:**

1. Read the "max_emails" value from the input context.
2. Call bulk_fetch_emails with max_emails set to that value.
3. The tool returns a JSON object with a "filename" key (e.g. {"filename": "emails.jsonl"}).
4. Call set_output("emails", <the filename value from the tool result>).

Do NOT add commentary or explanation. Do NOT call any other tools. Execute the steps above exactly.
""",
    tools=["bulk_fetch_emails"],
)

# Node 3: Classify and Act
# Applies user rules to each email and executes the appropriate Gmail actions.
classify_and_act_node = NodeSpec(
    id="classify-and-act",
    name="Classify and Act",
    description=(
        "Apply the user's rules to each email and execute "
        "the appropriate Gmail actions."
    ),
    node_type="event_loop",
    client_facing=False,
    input_keys=["rules", "emails"],
    output_keys=["actions_taken"],
    system_prompt="""\
You are an inbox management assistant. Apply the user's rules to their emails and execute Gmail actions.

**YOUR TOOLS:**
- load_data(filename, limit, offset) — Read emails from a local file. This is how you access the emails.
- append_data(filename, data) — Append a line to a file. Use this to record actions taken.
- gmail_batch_modify_messages(message_ids, add_labels, remove_labels) — Modify Gmail labels in batch. ALWAYS prefer this.
- gmail_modify_message(message_id, add_labels, remove_labels) — Modify a single message's labels.
- gmail_trash_message(message_id) — Move a message to trash. No batch version; call per email.
- set_output(key, value) — Set an output value. Call ONLY after all actions are executed.

**CONTEXT:**
- "rules" = the user's rule to apply (e.g. "mark all as unread")
- "emails" = a filename (e.g. "emails.jsonl") containing the fetched emails as JSONL. Each line has: id, subject, from, to, date, snippet, labels.

**STEP 1 — LOAD EMAILS (your first tool call MUST be load_data):**
Call load_data(filename=<the "emails" value from context>) to read the email data.
- If the result is empty, call set_output("actions_taken", "no emails to process") and stop.
- If has_more=true, load more pages with load_data(filename=..., offset=...) until all emails are loaded.

**STEP 2 — DETERMINE STRATEGY:**
- **Blanket rule** (same action for ALL emails, e.g. "mark all as unread"): Collect all message IDs, then execute ONE gmail_batch_modify_messages call.
- **Classification rule** (different actions for different emails): Classify each email, group by action, execute batch operations per group.

**STEP 3 — EXECUTE ACTIONS:**
Call the appropriate Gmail tool(s) with the real message IDs from the loaded emails. Then record each action:
- append_data(filename="actions.jsonl", data=<JSON of {email_id, subject, from, action}>)

**STEP 4 — FINISH:**
After ALL actions are executed, call set_output("actions_taken", "actions.jsonl").

**GMAIL LABEL REFERENCE:**
- MARK AS UNREAD — add_labels=["UNREAD"]
- MARK AS READ — remove_labels=["UNREAD"]
- MARK IMPORTANT — add_labels=["IMPORTANT"]
- REMOVE IMPORTANT — remove_labels=["IMPORTANT"]
- STAR — add_labels=["STARRED"]
- UNSTAR — remove_labels=["STARRED"]
- ARCHIVE — remove_labels=["INBOX"]
- MARK AS SPAM — add_labels=["SPAM"], remove_labels=["INBOX"]
- TRASH — use gmail_trash_message(message_id) per email

**CRITICAL RULES:**
- Your FIRST tool call MUST be load_data. Do NOT skip this.
- You MUST call Gmail tools to execute real actions. Do NOT just report what should be done.
- Do NOT call set_output until all Gmail actions are executed.
- Pass ONLY the filename "actions.jsonl" to set_output, NOT raw data.
""",
    tools=["gmail_trash_message", "gmail_modify_message", "gmail_batch_modify_messages", "load_data", "append_data"],
)

# Node 4: Report
# Generates a summary report of all actions taken.
report_node = NodeSpec(
    id="report",
    name="Report",
    description="Generate a summary report of all actions taken on the emails.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["actions_taken"],
    output_keys=["summary_report"],
    system_prompt="""\
You are an inbox management assistant. Your job is to generate a clear summary report of the actions taken on the user's emails.

**LOADING ACTIONS:**
The "actions_taken" value from context is a filename (e.g. "actions.jsonl"), NOT raw action data.
- If it equals "[]", there are no actions — generate a report stating no emails were processed and call set_output.
- Otherwise, call load_data(filename=<the actions_taken value>) to read the action records.
- The file is in JSONL format: each line is one JSON object with: email_id, subject, from, action.
- If load_data returns has_more=true, call it again with the next offset to get more records.
- Read ALL records before generating the report.

**GENERATE a summary report:**

1. **Overview** — Total emails processed, breakdown by action type.

2. **By Action** — Group emails by action taken. For each action group, list the emails with subject and sender.

3. **No Action Taken** — Any emails that didn't match any rules (if applicable).

Format the report as clean, readable text (not JSON).

After generating the report, call:
- set_output("summary_report", <the formatted report text>)
""",
    tools=["load_data"],
)

__all__ = [
    "intake_node",
    "fetch_emails_node",
    "classify_and_act_node",
    "report_node",
]
