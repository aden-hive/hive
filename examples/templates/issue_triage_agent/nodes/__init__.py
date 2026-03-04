"""Node definitions for Issue Triage Agent."""

from framework.graph import NodeSpec


intake_node = NodeSpec(
    id="intake",
    name="Triage Intake",
    description=(
        "Collect repository/channel scope and triage policy from the operator before intake"
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[
        "github_owner",
        "github_repo",
        "discord_channel_ids",
        "gmail_query",
        "triage_policy",
        "lookback_hours",
    ],
    output_keys=[
        "github_owner",
        "github_repo",
        "discord_channel_ids",
        "gmail_query",
        "triage_policy",
        "lookback_hours",
    ],
    nullable_output_keys=["gmail_query"],
    success_criteria=(
        "Scope and triage policy are explicit and executable across all channels"
    ),
    system_prompt="""\
You are an issue triage intake specialist.

Goal:
Capture one clear triage configuration that can be executed immediately.

STEP 1 (message only, no tools):
- Confirm or collect required inputs:
  - github_owner
  - github_repo
  - discord_channel_ids (comma-separated IDs)
  - lookback_hours (default 24)
  - triage_policy (severity and routing rules)
- gmail_query is optional. If omitted, default to recent inbox messages.
- Keep this brief; ask only what is missing.
- Use ask_user() when waiting for user input.

STEP 2 (after user confirms):
- set_output("github_owner", "...")
- set_output("github_repo", "...")
- set_output("discord_channel_ids", "...")
- set_output("gmail_query", "...")
- set_output("triage_policy", "...")
- set_output("lookback_hours", "...")
""",
    tools=[],
)


fetch_signals_node = NodeSpec(
    id="fetch-signals",
    name="Fetch Cross-Channel Signals",
    description=(
        "Gather candidate issues from GitHub issues, Discord channel messages, and Gmail"
    ),
    node_type="event_loop",
    max_node_visits=0,
    input_keys=[
        "github_owner",
        "github_repo",
        "discord_channel_ids",
        "gmail_query",
        "lookback_hours",
    ],
    output_keys=["raw_github_issues", "raw_discord_messages", "raw_emails"],
    nullable_output_keys=["gmail_query"],
    success_criteria=(
        "Fetches relevant records from all configured channels and stores structured raw data"
    ),
    system_prompt="""\
You gather triage signals.

Required behavior:
1. GitHub:
   - Call github_list_issues(owner=<github_owner>, repo=<github_repo>, state="open").
   - Keep issues that appear active/recent relative to lookback_hours.
2. Discord:
   - Parse discord_channel_ids into a list.
   - For each channel id, call discord_get_messages(channel_id=<id>, limit=50).
3. Gmail:
   - If gmail_query is provided, call gmail_list_messages(query=<gmail_query>, max_results=50).
   - Otherwise use a recency query like newer_than:2d with max_results=50.
   - For each selected message, call gmail_get_message(message_id=...).

Output format:
- set_output("raw_github_issues", <JSON string list with id/title/body/url/labels/comments/updated_at>)
- set_output("raw_discord_messages", <JSON string list with channel_id/message_id/author/content/timestamp>)
- set_output("raw_emails", <JSON string list with message_id/from/subject/snippet/date/body_summary>)

Rules:
- Use only the tools listed.
- If one source is temporarily unavailable, continue with the others and note it in the output payload.
""",
    tools=[
        "github_list_issues",
        "discord_get_messages",
        "gmail_list_messages",
        "gmail_get_message",
    ],
)


triage_and_route_node = NodeSpec(
    id="triage-and-route",
    name="Triage And Route",
    description=(
        "Normalize signals into issue records, assign severity/category/owner, and apply actions"
    ),
    node_type="event_loop",
    max_node_visits=0,
    input_keys=[
        "github_owner",
        "github_repo",
        "triage_policy",
        "raw_github_issues",
        "raw_discord_messages",
        "raw_emails",
    ],
    output_keys=["triage_report", "routed_count", "escalated_count"],
    success_criteria=(
        "Every candidate issue has severity, category, confidence, and at least one routing action"
    ),
    system_prompt="""\
You are the triage engine.

Task:
1. Parse raw_github_issues, raw_discord_messages, and raw_emails.
2. Deduplicate related reports into unified issue clusters.
3. For each cluster, assign:
   - category: bug | feature_request | support_question | incident
   - severity: P0 | P1 | P2 | P3
   - confidence: high | medium | low
   - rationale
4. Apply triage_policy for routing decisions.

Actions to perform:
- For GitHub issues tied to high-severity clusters, call github_update_issue to add labels
  such as "triaged", "severity:P0".."severity:P3", and category labels.
- For Discord-origin clusters, post a concise acknowledgment in Discord via discord_send_message
  with severity and next action.
- For email-origin clusters that require follow-up, create a Gmail draft reply with gmail_create_draft.

Output requirements:
- set_output("triage_report", "Markdown table of unified issues with source links, severity, owner, next action")
- set_output("routed_count", "<number>")
- set_output("escalated_count", "<number of P0/P1 items>")

Safety rules:
- Do not close issues automatically.
- Do not send emails directly; drafts only.
- If data is incomplete, mark confidence low and continue.
""",
    tools=[
        "github_update_issue",
        "discord_send_message",
        "gmail_create_draft",
    ],
)


report_node = NodeSpec(
    id="report",
    name="Triage Report",
    description="Present triage summary to the operator and capture the next requested action",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["triage_report", "routed_count", "escalated_count"],
    output_keys=["delivery_status", "next_action"],
    success_criteria="Operator receives triage summary and confirms next step",
    system_prompt="""\
Present the triage result clearly.

STEP 1 (message only):
- Share triage_report in a concise format.
- Include routed_count and escalated_count.
- Ask what to do next:
  - run_again
  - refine_policy
  - stop
- Use ask_user() to wait for response.

STEP 2:
- set_output("delivery_status", "completed")
- set_output("next_action", "run_again" | "refine_policy" | "stop")
""",
    tools=[],
)


__all__ = [
    "intake_node",
    "fetch_signals_node",
    "triage_and_route_node",
    "report_node",
]
