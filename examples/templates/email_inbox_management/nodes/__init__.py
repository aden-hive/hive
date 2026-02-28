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
    max_node_visits=0,
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
- **Draft replies** — create draft reply emails (never sent automatically)
- **Create/apply custom labels** — create new Gmail labels and apply them to emails

Present the rules back to the user in plain language. Do NOT refuse rules — if the user asks for any of the above actions, confirm you will do it.

Also confirm the batch size (max_emails). If max_emails is not provided, default to 100.

Ask the user to confirm: "Does this look right? I'll proceed once you confirm."

**STEP 2 — Show existing labels (tool call):**

Call gmail_list_labels() to show the user their current Gmail labels. This helps them reference existing labels or decide whether new custom labels are needed for their rules.

**STEP 3 — After the user confirms, call set_output:**

- set_output("rules", <the confirmed rules as a clear text description>)
- set_output("max_emails", <the confirmed max_emails as a string number, e.g. "100">)

""",
    tools=["gmail_list_labels"],
)

# Node 2: Fetch Emails (event_loop — fetches emails with pagination support)
# Uses bulk_fetch_emails for first fetch, gmail_list_messages + gmail_batch_get_messages
# for subsequent "next batch" fetches in continuous mode.
fetch_emails_node = NodeSpec(
    id="fetch-emails",
    name="Fetch Emails",
    description=(
        "Fetch emails from the Gmail inbox up to the configured batch limit. "
        "Supports pagination for continuous mode — can fetch the next batch "
        "of emails beyond what was already processed."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["rules", "max_emails"],
    output_keys=["emails"],
    system_prompt="""\
You are a data pipeline step. Your job is to fetch emails from Gmail and write them to emails.jsonl.

**FIRST-TIME FETCH (default path):**
1. Read "max_emails" and "rules" from input context.
2. Call bulk_fetch_emails(max_emails=<value>).
3. The tool returns {"filename": "emails.jsonl"}.
4. Call set_output("emails", "emails.jsonl").

**NEXT-BATCH FETCH (when user asks for "the next N" emails):**
The user wants emails BEYOND what was already fetched. Use pagination:
1. Call gmail_list_messages(query="label:INBOX", max_results=<previous + new count>).
   Use page_token if needed to paginate past already-fetched emails.
2. Identify message IDs NOT in the previous batch.
3. Call gmail_batch_get_messages(message_ids=<new_ids>, format="metadata").
4. For each message, call append_data(filename="emails.jsonl",
   data=<JSON: {id, subject, from, to, date, snippet, labels}>).
5. Call set_output("emails", "emails.jsonl").

**TOOLS:**
- bulk_fetch_emails(max_emails) — Bulk fetch from inbox, writes emails.jsonl.
- gmail_list_messages(query, max_results, page_token) — List message IDs.
- gmail_batch_get_messages(message_ids, format) — Fetch metadata (max 50/call).
- append_data(filename, data) — Append a line to a JSONL file.

Do NOT add commentary or explanation. Execute the appropriate path and call set_output when done.
""",
    tools=[
        "bulk_fetch_emails",
        "gmail_list_messages",
        "gmail_batch_get_messages",
        "append_data",
    ],
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
    max_node_visits=0,
    input_keys=["rules", "emails"],
    output_keys=["actions_taken"],
    system_prompt="""\
You are an inbox management assistant. Apply the user's rules to their emails and execute Gmail actions.

**YOUR TOOLS:**
- load_data(filename, limit, offset) — Read emails from a local file.
- append_data(filename, data) — Append a line to a file. Record actions taken.
- gmail_batch_modify_messages(message_ids, add_labels, remove_labels) — Modify labels in batch. ALWAYS prefer this.
- gmail_modify_message(message_id, add_labels, remove_labels) — Modify a single message's labels.
- gmail_trash_message(message_id) — Move a message to trash.
- gmail_create_draft(to, subject, body) — Create a draft reply. NEVER sends automatically.
- gmail_create_label(name) — Create a new Gmail label. Returns the label ID.
- gmail_list_labels() — List all existing Gmail labels with their IDs.
- set_output(key, value) — Set an output value. Call ONLY after all actions are executed.

**CONTEXT:**
- "rules" = the user's rule to apply (e.g. "mark all as unread").
- "emails" = a filename (e.g. "emails.jsonl") containing the fetched emails as JSONL.
  Each line has: id, subject, from, to, date, snippet, labels.

**PROCESS EMAILS ONE CHUNK AT A TIME (you will get multiple turns):**

Each turn, process exactly ONE chunk: load → classify → act → record. Then STOP and wait for your next turn to load the next chunk.

1. Call load_data(filename=<emails value>, limit_bytes=7500).
   - Parse the visible JSONL lines: split by \n, JSON.parse each complete line.
   - Ignore the last line if it appears cut off (incomplete JSON).
   - Note the next_offset_bytes value from the result.

2. Classify the emails in THIS chunk against the rules. For each email, decide the action: trash, draft reply, label change, or no action.

3. Execute Gmail actions for this chunk immediately:
   - **Label changes:** gmail_batch_modify_messages for all IDs in this chunk that need the same label change.
   - **Trash:** gmail_trash_message per email.
   - **Drafts:** gmail_create_draft per email.
   - Record each action: append_data(filename="actions.jsonl", data=<JSON of {email_id, subject, from, action}>)

4. If has_more=true, STOP HERE. On your next turn, call load_data with offset_bytes=<next_offset_bytes> and repeat from step 2.
   If has_more=false, you are done processing — call set_output("actions_taken", "actions.jsonl").

**CRITICAL:** Only call load_data ONCE per turn. Do NOT pre-load multiple chunks. You must see the emails before you can act on them.

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
- DRAFT REPLY — use gmail_create_draft(to=<sender>, subject="Re: <subject>", body=<contextual reply based on email content>). Creates a draft only, never sends.
- CREATE CUSTOM LABEL — use gmail_create_label(name=<label_name>) to create, then apply via gmail_modify_message with add_labels=[<label_id>]
- APPLY CUSTOM LABEL — add_labels=[<label_id>] using the ID from gmail_create_label or gmail_list_labels

**CRITICAL RULES:**
- Your FIRST tool call MUST be load_data. Do NOT skip this.
- You MUST call Gmail tools to execute real actions. Do NOT just report what should be done.
- Do NOT call set_output until all Gmail actions are executed.
- Pass ONLY the filename "actions.jsonl" to set_output, NOT raw data.
- NEVER send emails. Only create drafts via gmail_create_draft.
""",
    tools=[
        "gmail_trash_message",
        "gmail_modify_message",
        "gmail_batch_modify_messages",
        "gmail_create_draft",
        "gmail_create_label",
        "gmail_list_labels",
        "load_data",
        "append_data",
    ],
)

# Node 4: Report
# Generates a summary report of all actions taken.
report_node = NodeSpec(
    id="report",
    name="Report",
    description="Generate a summary report of all actions taken on the emails and present it to the user.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["actions_taken"],
    output_keys=["summary_report"],
    system_prompt="""\
You are an inbox management assistant. Your job is to generate a clear summary report of the actions taken on the user's emails, present it, and ask if they want to run another batch.

**STEP 1 — Load actions and generate the report (tool calls first):**

The "actions_taken" value from context is a filename (e.g. "actions.jsonl"), NOT raw action data.
- If it equals "[]", there are no actions — skip to STEP 2 with a message that no emails were processed.
- Otherwise, call load_data(filename=<the actions_taken value>) to read the action records.
- The file is in JSONL format: each line is one JSON object with: email_id, subject, from, action.
- If load_data returns has_more=true, call it again with the next offset to get more records.
- Read ALL records before generating the report.

**STEP 2 — Present the report to the user (text only, NO tool calls):**

Present a clean, readable summary:

1. **Overview** — Total emails processed, breakdown by action type.

2. **By Action** — Group emails by action taken. For each action group, list the emails with subject and sender.

3. **No Action Taken** — Any emails that didn't match any rules (if applicable).

Then ask: "Would you like to run another inbox triage with new rules?"

**STEP 3 — After the user responds, call set_output:**
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
