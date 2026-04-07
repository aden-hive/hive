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
    output_keys=["rules", "max_emails", "query"],
    nullable_output_keys=["query"],
    system_prompt="""\
You are an inbox management assistant. The user has provided rules for managing their emails.

**RULES ARE ADDITIVE.** If existing rules are already present in context from a previous cycle,
present ALL of them (old + new). The user can add, modify, or remove rules. When calling
set_output("rules", ...), include ALL active rules — old and new combined.

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

Also confirm the page size (max_emails). If max_emails is not provided, default to 100.
Note: max_emails is the page size per fetch cycle. The agent will loop through ALL inbox emails
by fetching max_emails at a time until no more remain.

Ask the user to confirm: "Does this look right? I'll proceed once you confirm."

**STEP 2 — Show existing labels (tool call):**

Call gmail_list_labels() to show the user their current Gmail labels. This helps them reference existing labels or decide whether new custom labels are needed for their rules.

**STEP 3 — After the user confirms, call set_output:**

- set_output("rules", <ALL active rules as a clear text description>)
- set_output("max_emails", <the confirmed max_emails as a string number, e.g. "100">)
- set_output("query", <Gmail search query if the user wants to target specific emails>)

**TARGETED QUERY (optional):**

If the user's rules target specific emails (e.g. "delete all emails from newsletters@example.com"),
build a Gmail search query to fetch ONLY matching emails instead of the entire inbox. This is much
faster and more efficient.

Gmail search query syntax:
- `from:sender@example.com` — from a specific sender
- `to:recipient@example.com` — to a specific recipient
- `subject:keyword` — subject contains keyword
- `is:unread` / `is:read` — read status
- `is:starred` / `is:important` — flags
- `has:attachment` — has attachments
- `filename:pdf` — attachment filename
- `label:LABEL_NAME` — has a specific label
- `category:promotions` / `category:social` / `category:updates` — Gmail categories
- `newer_than:7d` / `older_than:30d` — relative time (d=days, m=months, y=years)
- `after:2024/01/01` / `before:2024/12/31` — absolute dates
- Combine with spaces (AND): `from:boss@co.com subject:urgent`
- OR operator: `from:alice OR from:bob`
- NOT / exclude: `-from:noreply@example.com` or `NOT from:noreply`
- Grouping: `{from:alice from:bob}` (same as OR)

Examples:
- User says "trash all promotional emails" → query: `category:promotions`
- User says "star emails from my boss jane@co.com" → query: `from:jane@co.com`
- User says "mark unread emails older than a week as read" → query: `is:unread older_than:7d`
- User says "apply rules to all inbox emails" → no query needed (default: `label:INBOX`)

If the rules apply broadly to ALL emails, do NOT set a query — the default `label:INBOX` will be used.
Only set a query when it would meaningfully narrow the search.

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
        "Fetch one page of emails from Gmail inbox. Returns emails filename "
        "and next_page_token for pagination. The graph loops back here if "
        "more pages remain."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=[
        "rules",
        "max_emails",
        "next_page_token",
        "last_processed_timestamp",
        "query",
    ],
    output_keys=["emails", "next_page_token"],
    nullable_output_keys=["next_page_token"],
    system_prompt="""\
You are a data pipeline step. Your job is to fetch ONE PAGE of emails from Gmail.

**INSTRUCTIONS:**
1. Read "max_emails", "next_page_token", "last_processed_timestamp", and "query" from input context.
2. Call bulk_fetch_emails with:
   - max_emails=<max_emails value, default "100">
   - page_token=<next_page_token value, if present and non-empty>
   - after_timestamp=<last_processed_timestamp value, if present and non-empty>
   - query=<query value, if present and non-empty; omit to default to "label:INBOX">
3. The tool returns {"filename": "emails.jsonl", "count": N, "next_page_token": "<token or null>"}.
4. Call set_output("emails", "emails.jsonl").
5. Call set_output("next_page_token", <the next_page_token from the tool result, or "" if null>).

**IMPORTANT:** The graph will automatically loop back to this node if next_page_token is non-empty.
You only need to fetch ONE page per visit. Do NOT loop internally.

Do NOT add commentary or explanation. Execute the steps and call set_output when done.
""",
    tools=[
        "bulk_fetch_emails",
    ],
)

# Node 3: Classify and Act
# Applies user rules to each email and executes the appropriate Gmail actions.
classify_and_act_node = NodeSpec(
    id="classify-and-act",
    name="Classify and Act",
    description=("Apply the user's rules to each email and execute the appropriate Gmail actions."),
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
- gmail_batch_modify_messages(message_ids, add_labels, remove_labels) — Modify labels in batch. ONLY call when BOTH add_labels AND remove_labels are non-empty lists. If only one type is needed, use gmail_modify_message instead.
- gmail_modify_message(message_id, add_labels, remove_labels) — Modify a single message's labels. Use when you have only add_labels OR only remove_labels (not both).
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
- MARK AS UNREAD — add_labels=["UNREAD"] via gmail_modify_message (single action)
- MARK AS READ — remove_labels=["UNREAD"] via gmail_modify_message
- MARK IMPORTANT — add_labels=["IMPORTANT"] via gmail_modify_message
- REMOVE IMPORTANT — remove_labels=["IMPORTANT"] via gmail_modify_message
- STAR — add_labels=["STARRED"] via gmail_modify_message
- UNSTAR — remove_labels=["STARRED"] via gmail_modify_message
- ARCHIVE — remove_labels=["INBOX"] via gmail_modify_message (single email) OR gmail_batch_modify_messages (multiple emails ALL need archive)
- MARK AS SPAM — add_labels=["SPAM"], remove_labels=["INBOX"] — must use gmail_modify_message for single emails or gmail_batch_modify_messages for multiple
- TRASH — use gmail_trash_message(message_id) per email
- DRAFT REPLY — use gmail_create_draft(to=<sender>, subject="Re: <subject>", body=<contextual reply based on email content>). Creates a draft only, never sends.
- CREATE CUSTOM LABEL — use gmail_create_label(name=<label_name>) to create, then apply via gmail_modify_message with add_labels=[<label_id>]
- APPLY CUSTOM LABEL — add_labels=[<label_id>] using the ID from gmail_create_label or gmail_list_labels

**KEY RULE:** When you have BOTH add_labels AND remove_labels (like marking as spam), use gmail_modify_message for single emails or gmail_batch_modify_messages for multiple. When you have ONLY add_labels OR ONLY remove_labels (like just archiving), you MUST use gmail_modify_message because gmail_batch_modify_messages will fail.

**QUEEN RULE INJECTION:**
If a new rule appears in the conversation mid-processing (injected by the queen),
apply it to the remaining unprocessed emails alongside the existing rules.

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
    input_keys=["actions_taken", "rules"],
    output_keys=["summary_report", "rules", "last_processed_timestamp"],
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

Then ask: "Would you like to run another inbox management cycle with new rules?"

**STEP 3 — After the user responds, call set_output to persist state:**
- set_output("summary_report", <the formatted report text>)
- set_output("rules", <the current rules from context — pass them through unchanged so they persist for the next cycle>)
- Call get_current_timestamp() and set_output("last_processed_timestamp", <the returned timestamp>)

This ensures the next timer cycle knows when emails were last processed and which rules to apply.
""",
    tools=["load_data", "get_current_timestamp"],
)

__all__ = [
    "intake_node",
    "fetch_emails_node",
    "classify_and_act_node",
    "report_node",
]
