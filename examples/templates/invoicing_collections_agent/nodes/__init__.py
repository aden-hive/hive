"""Node definitions for Invoicing & Collections Agent."""

from framework.graph import NodeSpec

# Node 1: Scan invoices from CSV
scan_invoices_node = NodeSpec(
    id="scan-invoices",
    name="Scan Invoices",
    description=(
        "Read the invoice CSV file and query for unpaid invoices "
        "with computed days_overdue relative to the current date."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["invoice_file_path"],
    output_keys=["all_invoices", "invoice_count", "scan_summary"],
    system_prompt="""\
You are an accounts-receivable assistant. Your job is to load an invoice file
and identify all unpaid invoices.

Steps:
1. Use csv_read to inspect the file at {invoice_file_path} and understand its
   column structure.
2. Use csv_sql to run a query that:
   - Filters to rows where status != 'paid'
   - Computes days_overdue as the number of days between due_date and
     CURRENT_DATE (use CURRENT_DATE in the SQL).
   - Orders results by days_overdue DESC.

Return your output as raw JSON (no markdown):
{{
  "all_invoices": [
    {{
      "invoice_id": "...",
      "customer_name": "...",
      "customer_email": "...",
      "amount": 0.0,
      "issue_date": "...",
      "due_date": "...",
      "status": "...",
      "description": "...",
      "days_overdue": 0
    }}
  ],
  "invoice_count": 0,
  "scan_summary": "Found N unpaid invoices totalling $X."
}}
""",
    tools=["csv_read", "csv_sql"],
)

# Node 2: Classify overdue invoices into aging buckets
classify_overdue_node = NodeSpec(
    id="classify-overdue",
    name="Classify Overdue",
    description=(
        "Bucket each unpaid invoice into aging categories (current / 30-day / "
        "60-day / 90+) using the collection config thresholds. Flag invoices "
        "for reminder or escalation."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=3,
    input_keys=["all_invoices", "collection_config"],
    output_keys=[
        "classified_invoices",
        "reminder_accounts",
        "escalation_accounts",
        "classification_summary",
    ],
    system_prompt="""\
You are an accounts-receivable analyst. Classify each invoice into an aging
bucket and determine the correct action.

Invoices: {all_invoices}
Collection config: {collection_config}

Rules:
- Use the aging_buckets in the config to assign each invoice to a bucket
  based on its days_overdue value.
- If an invoice's amount >= escalation_threshold_usd, it MUST be flagged for
  escalation regardless of its bucket.
- Invoices in the "current" bucket (0-30 days) must NEVER receive reminders.
- Invoices flagged for "first_reminder" or "second_reminder" go into
  reminder_accounts.
- Invoices flagged for "escalate" (90+ days or high-value) go into
  escalation_accounts.

Return raw JSON (no markdown):
{{
  "classified_invoices": [
    {{
      "invoice_id": "...",
      "customer_name": "...",
      "customer_email": "...",
      "amount": 0.0,
      "days_overdue": 0,
      "bucket": "current|30_day|60_day|90_plus",
      "action": "none|first_reminder|second_reminder|escalate"
    }}
  ],
  "reminder_accounts": [
    {{
      "invoice_id": "...",
      "customer_name": "...",
      "customer_email": "...",
      "amount": 0.0,
      "days_overdue": 0,
      "action": "first_reminder|second_reminder"
    }}
  ],
  "escalation_accounts": [
    {{
      "invoice_id": "...",
      "customer_name": "...",
      "customer_email": "...",
      "amount": 0.0,
      "days_overdue": 0,
      "reason": "90+ days overdue|High-value invoice (>$10k)"
    }}
  ],
  "classification_summary": "Classified N invoices: X current, Y at 30-day, ..."
}}
""",
    tools=[],
)

# Node 3: Send reminder emails
send_reminders_node = NodeSpec(
    id="send-reminders",
    name="Send Reminders",
    description=(
        "Send first or second reminder emails to accounts in the reminder "
        "list. Handle missing email credentials gracefully."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["reminder_accounts", "collection_config"],
    output_keys=["reminders_sent", "reminder_errors", "reminder_summary"],
    system_prompt="""\
You are an accounts-receivable assistant sending overdue invoice reminders.

Accounts to remind: {reminder_accounts}
Collection config: {collection_config}

For each account in reminder_accounts:
1. Look up the email template from collection_config.email_templates based on
   the account's action (first_reminder or second_reminder).
2. Use the send_email tool to send the reminder:
   - to: the customer_email
   - subject: use the template subject, replacing {{invoice_id}} with the
     actual invoice ID
   - html: compose a professional email body. For first_reminder use a polite
     tone; for second_reminder use a firm but respectful tone. Include the
     invoice ID, amount, and days overdue.
   - from_email: use collection_config.from_email
3. If send_email fails (e.g. missing credentials), log the error but continue
   with the next account — do NOT stop the whole process.

Return raw JSON (no markdown):
{{
  "reminders_sent": [
    {{
      "invoice_id": "...",
      "customer_email": "...",
      "action": "first_reminder|second_reminder",
      "status": "sent|failed",
      "error": null
    }}
  ],
  "reminder_errors": [
    {{
      "invoice_id": "...",
      "error": "..."
    }}
  ],
  "reminder_summary": "Sent N reminders, M failures."
}}
""",
    tools=["send_email"],
)

# Node 4: Judge reminder quality and classification accuracy
judge_reminders_node = NodeSpec(
    id="judge-reminders",
    name="Judge Reminders",
    description=(
        "Validate that invoice classification matches config rules and that "
        "reminders targeted the correct accounts. Flag misclassifications."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=[
        "classified_invoices",
        "reminders_sent",
        "reminder_accounts",
        "escalation_accounts",
        "collection_config",
    ],
    output_keys=[
        "judgment_passed",
        "needs_reclassification",
        "judgment_details",
        "misclassified_invoices",
    ],
    system_prompt="""\
You are a quality-assurance reviewer for an accounts-receivable process.

Classified invoices: {classified_invoices}
Reminders sent: {reminders_sent}
Reminder accounts: {reminder_accounts}
Escalation accounts: {escalation_accounts}
Collection config: {collection_config}

Verify ALL of the following:
1. No invoice in the "current" bucket (0-30 days) received a reminder.
2. Every invoice with days_overdue 31-60 is bucketed as "30_day" with action
   "first_reminder".
3. Every invoice with days_overdue 61-90 is bucketed as "60_day" with action
   "second_reminder".
4. Every invoice with days_overdue 91+ is bucketed as "90_plus" with action
   "escalate".
5. Every invoice with amount >= escalation_threshold_usd appears in
   escalation_accounts regardless of its bucket.
6. Reminders were only sent to accounts in reminder_accounts.

If ANY rule is violated:
- Set judgment_passed to false and needs_reclassification to true.
- List the misclassified invoices with the rule that was violated.

If all rules pass:
- Set judgment_passed to true and needs_reclassification to false.

Return raw JSON (no markdown):
{{
  "judgment_passed": true,
  "needs_reclassification": false,
  "judgment_details": "All N invoices correctly classified. Reminders valid.",
  "misclassified_invoices": []
}}
""",
    tools=[],
)

# Node 5: Human-in-the-loop escalation review (client-facing)
escalate_review_node = NodeSpec(
    id="escalate-review",
    name="Escalation Review",
    description=(
        "Present escalation accounts to a human reviewer for approval. "
        "Pauses execution until the reviewer decides."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["escalation_accounts", "classified_invoices", "judgment_details"],
    output_keys=["approval_result", "reviewer_notes", "approved_accounts"],
    system_prompt="""\
The following invoices require human review before further collection action.
They have been flagged for escalation due to high value (>$10,000) or being
severely overdue (90+ days).

Escalation accounts: {escalation_accounts}
Classification details: {classified_invoices}
Judgment details: {judgment_details}

Please review each account and decide:
- "approved" — proceed with escalated collection actions
- "rejected" — do not escalate; no further action
- "deferred" — revisit later

Provide any notes for the collections team.
""",
    tools=[],
)

# Node 6: Generate AR aging report
generate_report_node = NodeSpec(
    id="generate-report",
    name="Generate Report",
    description=(
        "Build an accounts-receivable aging summary CSV with per-bucket "
        "totals and save it to disk."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=[
        "classified_invoices",
        "reminders_sent",
        "escalation_accounts",
        "approval_result",
        "reviewer_notes",
    ],
    output_keys=["report_file_path", "report_summary", "ar_aging_totals"],
    system_prompt="""\
You are a financial reporting assistant. Generate an AR aging report.

Classified invoices: {classified_invoices}
Reminders sent: {reminders_sent}
Escalation accounts: {escalation_accounts}
Approval result: {approval_result}
Reviewer notes: {reviewer_notes}

Create a CSV report with these columns:
  invoice_id, customer_name, amount, days_overdue, bucket, action_taken,
  reminder_status, escalation_status, reviewer_decision

Use csv_write to save the report to "ar_aging_report.csv".

Also compute per-bucket totals:
  - current: count and total $
  - 30_day: count and total $
  - 60_day: count and total $
  - 90_plus: count and total $
  - grand total of all unpaid

Return raw JSON (no markdown):
{{
  "report_file_path": "ar_aging_report.csv",
  "report_summary": "Generated AR aging report with N invoices.",
  "ar_aging_totals": {{
    "current": {{"count": 0, "total": 0.0}},
    "30_day": {{"count": 0, "total": 0.0}},
    "60_day": {{"count": 0, "total": 0.0}},
    "90_plus": {{"count": 0, "total": 0.0}},
    "grand_total": 0.0
  }}
}}
""",
    tools=["csv_write"],
)

__all__ = [
    "scan_invoices_node",
    "classify_overdue_node",
    "send_reminders_node",
    "judge_reminders_node",
    "escalate_review_node",
    "generate_report_node",
]
