"""Node definitions for Gmail Inbox Guardian."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# User defines or updates email triage rules in plain language.
intake_node = NodeSpec(
    id="intake",
    name="Rule Setup",
    description=(
        "User defines or updates email triage rules in plain language. "
        "Rules persist in shared memory for event-driven processing."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[],
    output_keys=["rules", "max_emails"],
    system_prompt="""\
You are an inbox guardian assistant. The user will define rules for automatically triaging their Gmail inbox.

**STEP 1 — Respond to the user (text only, NO tool calls):**

Read what the user wants. They will describe rules in plain language like:
- "Star emails from my boss"
- "Spam anything from marketing newsletters"
- "Mark as read all notifications from GitHub"
- "Trash emails with 'unsubscribe' in the subject"

Present a clear summary of the rules you understood, mapped to Gmail actions:

Available Gmail actions:
- **Trash** emails
- **Mark as spam**
- **Mark as important** / unmark important
- **Mark as read** / mark as unread
- **Star** / unstar emails
- **Archive** (remove from inbox)
- **Add/remove Gmail labels** (INBOX, UNREAD, IMPORTANT, STARRED, SPAM, etc.)

Also confirm the batch size (max_emails). Default to 10 if not specified.

Ask the user to confirm: "Does this look right? I'll start applying these rules to incoming emails once you confirm."

If this is a RETURN VISIT (rules already exist in context), ask: "Your current rules are active. Would you like to modify them, or are they working well?"

**STEP 2 — After the user confirms, call set_output:**

- set_output("rules", <the confirmed rules as a clear text description>)
- set_output("max_emails", <the confirmed max_emails as a string number, e.g. "10">)""",
    tools=[],
)

# Node 2: Fetch Emails
# Fetches new emails from Gmail inbox up to the configured batch limit.
fetch_emails_node = NodeSpec(
    id="fetch-emails",
    name="Fetch Emails",
    description=(
        "Fetches new emails from Gmail inbox up to the configured batch limit. "
        "Writes email data to emails.jsonl for downstream processing."
    ),
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["rules", "max_emails"],
    output_keys=["emails"],
    system_prompt="""\
You are a data pipeline step. Your job is to fetch new emails from Gmail and write them to emails.jsonl.

**STEPS:**
1. Read "max_emails" from input context. Default to 10 if not set.
2. Call gmail_list_messages(query="label:INBOX is:unread", max_results=<max_emails>) to get message IDs.
3. If no messages found, call set_output("emails", "no_new_emails") and stop.
4. Call gmail_batch_get_messages(message_ids=<list of IDs>, format="metadata") to get full metadata.
5. For each message, call append_data(filename="emails.jsonl", data=<JSON: {id, subject, from, to, date, snippet, labels}>).
6. Call set_output("emails", "emails.jsonl").

Do NOT add commentary or explanation. Execute the steps and call set_output when done.""",
    tools=[
        "gmail_list_messages",
        "gmail_batch_get_messages",
        "append_data",
    ],
)

# Node 3: Classify and Act
# Applies the user's rules to each email and executes Gmail actions.
classify_and_act_node = NodeSpec(
    id="classify-and-act",
    name="Classify and Act",
    description=(
        "Applies the user's rules to each email and executes the appropriate "
        "Gmail actions (star, spam, trash, mark read/unread, label, etc.)."
    ),
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["rules", "emails"],
    output_keys=["actions_taken"],
    system_prompt="""\
You are an inbox guardian. Apply the user's rules to their emails and execute Gmail actions.

**YOUR TOOLS:**
- load_data(filename, offset_bytes, limit_bytes) — Read emails from a local file using byte-based pagination.
- append_data(filename, data) — Append a line to a file. Use this to record actions taken.
- gmail_batch_modify_messages(message_ids, add_labels, remove_labels) — Modify Gmail labels in batch. ALWAYS prefer this.
- gmail_modify_message(message_id, add_labels, remove_labels) — Modify a single message's labels.
- gmail_trash_message(message_id) — Move a message to trash. No batch version; call per email.
- set_output(key, value) — Set an output value. Call ONLY after all actions are executed.

**CONTEXT:**
- "rules" = the user's rules to apply (e.g. "star emails from my boss, spam newsletters")
- "emails" = a filename (e.g. "emails.jsonl") containing fetched emails as JSONL. Each line has: id, subject, from, to, date, snippet, labels.
- If "emails" equals "no_new_emails", call set_output("actions_taken", "no_new_emails") and stop.

**STEP 1 — LOAD EMAILS (your first tool call MUST be load_data):**
Call load_data(filename=<the "emails" value from context>, limit_bytes=10000) to read the email data.
- Parse the content as JSONL: split by \\n, then JSON.parse each line to get email objects.
- If has_more=true, load more pages with load_data(filename=..., offset_bytes=<next_offset_bytes>) until all emails are loaded.

**STEP 2 — CLASSIFY EACH EMAIL:**
For each email, determine which rule(s) apply based on sender, subject, snippet, and labels.
Group emails by the action to take.

**STEP 3 — EXECUTE ACTIONS:**
- **Blanket rule** (same action for ALL emails): Collect all message IDs, execute ONE gmail_batch_modify_messages call.
- **Mixed rules** (different actions): Group by action, execute batch operations per group.
- For trash: use gmail_trash_message(message_id) per email (no batch version).
- Record each action: append_data(filename="actions.jsonl", data=<JSON of {email_id, subject, from, action}>)

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
- Pass ONLY the filename "actions.jsonl" to set_output, NOT raw data.""",
    tools=[
        "gmail_trash_message",
        "gmail_modify_message",
        "gmail_batch_modify_messages",
        "load_data",
        "append_data",
    ],
)

# Node 4: Report (non-blocking)
# Generates a summary report and saves it. Does NOT block for user input.
report_node = NodeSpec(
    id="report",
    name="Report",
    description=(
        "Generates a summary report of all actions taken on emails. "
        "Non-blocking — saves the report and completes so the agent resumes listening."
    ),
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["actions_taken"],
    output_keys=["summary_report"],
    system_prompt="""\
You are an inbox guardian reporter. Generate a summary of the actions taken on emails.

**STEP 1 — Load actions:**
- If "actions_taken" equals "no_new_emails", call set_output("summary_report", "No new emails to process.") and stop.
- Otherwise, call load_data(filename=<the actions_taken value>, limit_bytes=10000) to read action records.
- The file is JSONL format: each line is {email_id, subject, from, action}.
- If has_more=true, load more pages until all records are read.

**STEP 2 — Generate and save the report:**
Create a clean summary:
1. **Overview** — Total emails processed, breakdown by action type.
2. **By Action** — Group emails by action taken. For each group, list email subjects and senders.

Save the report:
  save_data(filename="report.txt", data=<the formatted report text>)

**STEP 3 — Call set_output:**
  set_output("summary_report", <the formatted report text>)

Do NOT block for user input. Generate the report and finish immediately.""",
    tools=[
        "load_data",
        "save_data",
    ],
)

__all__ = [
    "intake_node",
    "fetch_emails_node",
    "classify_and_act_node",
    "report_node",
]
