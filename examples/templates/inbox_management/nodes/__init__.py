"""Node definitions for Inbox Management Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Receives triage rules and max_emails, confirms understanding with user.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description=(
        "Receive and validate input parameters: triage rules and max_emails. "
        "Present the interpreted rules back to the user for confirmation."
    ),
    node_type="event_loop",
    client_facing=True,
    input_keys=["rules", "max_emails"],
    output_keys=["triage_rules", "max_emails"],
    system_prompt="""\
You are an inbox management assistant. The user has provided triage rules for managing their unread emails.

**STEP 1 — Respond to the user (text only, NO tool calls):**

Read the user's triage rules from the input context. Present a clear summary of how you will categorize and act on their emails:

- What will be TRASHED (spam, unwanted)
- What will be ARCHIVED (low-priority, newsletters)
- What will be marked IMPORTANT (urgent, action-needed)
- How emails will be CATEGORIZED (Action Needed, FYI, Waiting On)

Also confirm the batch size (max_emails). If max_emails is not provided, default to 100.

Ask the user to confirm: "Does this look right? I'll proceed once you confirm."

**STEP 2 — After the user confirms, call set_output:**

- set_output("triage_rules", <the confirmed triage rules as a clear text description>)
- set_output("max_emails", <the confirmed max_emails as a string number, e.g. "100">)
""",
    tools=[],
)

# Node 2: Fetch Emails
# Fetches unread emails from Gmail up to the batch limit.
fetch_emails_node = NodeSpec(
    id="fetch-emails",
    name="Fetch Emails",
    description=(
        "Fetch unread emails from Gmail up to the configured batch limit. "
        "Only retrieves emails with the UNREAD label."
    ),
    node_type="event_loop",
    client_facing=False,
    input_keys=["triage_rules", "max_emails"],
    output_keys=["emails"],
    system_prompt="""\
You are an inbox management assistant. Your job is to fetch unread emails from Gmail.

**IMPORTANT CONSTRAINTS:**
- ONLY fetch emails that are UNREAD. Use the query "is:unread" with gmail_list_messages.
- Fetch at most the number specified in max_emails (from context).
- For each email returned by gmail_list_messages, use gmail_get_message to get its full details (subject, from, snippet, body, labels).

**PROCESS:**
1. Call gmail_list_messages with query "is:unread" and max_results set to the max_emails value.
2. For each message in the results, call gmail_get_message to get full details.
3. Collect all email data into a structured list.
4. Call set_output("emails", <JSON string of the email list>).

Each email in the list should include: id, subject, from, date, snippet, body (or body preview), and current labels.

If there are no unread emails, set_output("emails", "[]") — an empty list is valid.
""",
    tools=["gmail_list_messages", "gmail_get_message"],
)

# Node 3: Classify and Act
# Classifies each email and takes the appropriate Gmail action.
classify_and_act_node = NodeSpec(
    id="classify-and-act",
    name="Classify and Act",
    description=(
        "Classify each email against the user's triage rules, then execute "
        "the appropriate Gmail actions (trash, archive, mark important, add labels)."
    ),
    node_type="event_loop",
    client_facing=False,
    input_keys=["triage_rules", "emails"],
    output_keys=["actions_taken"],
    system_prompt="""\
You are an inbox management assistant. Your job is to classify emails and take action based on the user's triage rules.

**TRIAGE RULES** are provided in the context as "triage_rules". Apply these rules to each email.

**AVAILABLE ACTIONS:**
1. **TRASH** — For spam, unwanted emails. Use gmail_trash_message(message_id).
2. **ARCHIVE** — For low-priority, newsletters. Use gmail_modify_message(message_id, remove_labels=["INBOX"]) to remove from inbox but keep in All Mail.
3. **MARK IMPORTANT** — For urgent, action-needed emails. Use gmail_modify_message(message_id, add_labels=["IMPORTANT"]).
4. **CATEGORIZE** — Add urgency labels. Use gmail_modify_message(message_id, add_labels=[<category>]) where category is one of: "Action Needed", "FYI", "Waiting On".

**IMPORTANT CONSTRAINTS:**
- NEVER modify read emails. The emails list from context contains ONLY unread emails, so you are safe to act on all of them.
- Apply the MOST appropriate action to each email based on the rules.
- An email can have BOTH an action (trash/archive/mark important) AND a category (Action Needed/FYI/Waiting On) if appropriate — but trashed emails don't need a category.

**PROCESS:**
1. Read the emails list from context.
2. For each email, classify it against the triage rules.
3. Execute the appropriate Gmail action(s) for each email.
4. Track every action taken: {email_id, subject, from, classification, action, category}.
5. After processing ALL emails, call set_output("actions_taken", <JSON string of the actions list>).

If the emails list is empty, set_output("actions_taken", "[]").
""",
    tools=["gmail_trash_message", "gmail_modify_message", "gmail_batch_modify_messages"],
)

# Node 4: Report
# Generates a summary report of all triage actions taken.
report_node = NodeSpec(
    id="report",
    name="Report",
    description="Generate a summary report of all triage actions taken, organized by category.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["actions_taken"],
    output_keys=["summary_report"],
    system_prompt="""\
You are an inbox management assistant. Your job is to generate a clear summary report of the triage actions taken.

**READ the actions_taken list from context.** It contains objects with: email_id, subject, from, classification, action, category.

**GENERATE a summary report with these sections:**

1. **Overview** — Total emails processed, breakdown by action (trashed, archived, marked important, categorized only).

2. **Trashed** — List of emails that were trashed, with subject and sender.

3. **Archived** — List of emails that were archived, with subject and sender.

4. **Marked Important** — List of emails marked important, with subject and sender.

5. **By Category:**
   - **Action Needed** — Emails requiring user action
   - **FYI** — Informational emails
   - **Waiting On** — Emails waiting for a response from others

6. **No Action Taken** — Any emails that didn't match any rules (if applicable).

Format the report as clean, readable text (not JSON).

After generating the report, call:
- set_output("summary_report", <the formatted report text>)
""",
    tools=[],
)

__all__ = [
    "intake_node",
    "fetch_emails_node",
    "classify_and_act_node",
    "report_node",
]
