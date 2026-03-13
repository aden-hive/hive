"""Node definitions for GitHub Issue Triage Agent — 3-node pipeline."""

from framework.graph import NodeSpec

# Node 1: Fetch Issues
# owner and repo are guaranteed to be set and validated by agent.py before this node runs.
fetch_issues_node = NodeSpec(
    id="fetch_issues",
    name="Fetch Issues",
    description="Fetch open, un-triaged issues from the target GitHub repository",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["owner", "repo"],
    output_keys=["issues", "issue_count"],
    nullable_output_keys=["owner", "repo"],
    success_criteria=(
        "A list of un-triaged issues has been fetched from GitHub. "
        "Already-triaged issues (tracked in triaged_issues.json) are excluded. "
        "Pull requests returned by the issues endpoint are filtered out."
    ),
    system_prompt="""\
You are a GitHub issue fetcher. owner and repo are guaranteed to be valid — \
proceed directly.

IMPORTANT: owner is ONLY the GitHub username/org (e.g. "my-org"), NOT "owner/repo". \
repo is ONLY the repository name. Never combine them — always pass them as two separate arguments.

**PROCESS (follow exactly):**

**Step 1 — Load triage history:**
Call load_data(filename="triaged_issues.json").
CRITICAL: If the file does not exist or load_data returns ANY error, that is NORMAL \
and expected on the very first run. You MUST continue using an empty list []. \
DO NOT escalate to the queen. DO NOT treat this as a failure. \
Just use [] and move to Step 2 immediately.

**Step 2 — Fetch open issues:**
Call github_list_issues(owner=<owner>, repo=<repo>, state="open", limit=50).

**Step 3 — Filter:**
From the results, remove:
- Issues whose number is in the triaged list (already handled)
- Items that have a "pull_request" key (GitHub returns PRs in the issues endpoint)
- Issues that already have classification labels (bug, enhancement, question, \
duplicate, invalid)

**Step 4 — Enrich (if needed):**
For each remaining issue (up to 20), call github_get_issue to get the full body \
and existing labels if not already included in the list response.

**Step 5 — Output:**
Call set_output with the results:
- set_output("issues", <JSON array of issue objects with number, title, body, labels>)
- set_output("issue_count", <number of issues to triage>)

If there are no new issues to triage, set issues to [] and issue_count to 0.
""",
    tools=[
        "github_list_issues",
        "github_get_issue",
        "load_data",
    ],
)

# Node 2: Triage
# The LLM classifies each issue and applies labels + comments via the GitHub API.
triage_node = NodeSpec(
    id="triage",
    name="Triage Issues",
    description="Classify each issue, apply labels, and post triage comments",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["issues", "issue_count", "owner", "repo"],
    output_keys=["triage_summary"],
    success_criteria=(
        "Every issue in the batch has been classified. A triage comment has been "
        "attempted on each issue via github_create_comment, and a label applied via "
        "github_update_issue. If either call returns a permission error (403/Forbidden), "
        "the issue is still recorded as triaged with action 'read-only'. "
        "Triaged issue numbers have been persisted to triaged_issues.json."
    ),
    system_prompt="""\
You are a GitHub issue triage specialist. owner and repo are validated and correct.

**If issue_count is 0**, immediately call:
set_output("triage_summary", {"triaged": 0, "categories": {}, "message": \
"No new issues to triage."})
Then STOP.

**CLASSIFICATION RULES:**

| Category        | Label to apply | Action                                               |
|-----------------|----------------|------------------------------------------------------|
| Bug report      | bug            | Acknowledge, ask for repro steps if missing          |
| Feature request | enhancement    | Acknowledge, note it for team review                 |
| Question        | question       | Acknowledge, suggest relevant docs if possible       |
| Duplicate       | duplicate      | Reference the original issue, close with state="closed" |
| Invalid         | invalid        | Politely explain why, close with state="closed"      |
| Needs more info | needs-triage   | Ask reporter for missing details                     |

**PROCESS for each issue:**

1. **Read** the issue title and body carefully
2. **Classify** into one of the categories above
3. **Apply label** via github_update_issue(owner, repo, issue_number, labels=[<label>])
   - On permission error (403), record action as "read-only: label skipped" and continue.
4. **Post comment** via github_create_comment(owner, repo, issue_number, body=<comment>)
   - Compose a brief, polite triage comment. Be professional and helpful.
   - On permission error, record action as "read-only: comment skipped" and continue.
5. **Close if needed** — for duplicates and invalid issues ONLY, call \
github_update_issue with state="closed". Skip silently on permission error.
6. **Persist triage state BEFORE moving to the next issue:**
   a. Call load_data(filename="triaged_issues.json") — treat missing file as [].
   b. Append this issue's number to the list.
   c. Call save_data(filename="triaged_issues.json", data=<updated list as JSON string>).
   This ensures idempotency: if the agent stops mid-run, it won't re-triage this issue.

**CONSTRAINTS:**
- NEVER auto-close bug reports or feature requests
- Be polite and professional in all comments
- If unsure about classification, use "needs-triage" label
- Process issues in batches of 5 to respect rate limits
- On ANY tool error, record the error in the issue's action field and move on

**After processing all issues:**
Call set_output("triage_summary", {
  "triaged": <count>,
  "categories": {"bug": N, "enhancement": N, "question": N, ...},
  "issues": [{"number": N, "title": "...", "category": "...", "action": "..."}]
})
""",
    tools=[
        "github_create_comment",
        "github_update_issue",
        "github_get_issue",
        "load_data",
        "save_data",
    ],
)

# Node 3: Notify
# Sends a summary notification to Slack and/or Discord.
notify_node = NodeSpec(
    id="notify",
    name="Send Notifications",
    description="Send triage summary to Slack and/or Discord channels",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["triage_summary", "owner", "repo", "slack_channel", "discord_channel_id"],
    output_keys=["notification_status"],
    success_criteria=(
        "A triage summary notification has been successfully delivered to at least "
        "one configured channel (Slack or Discord). If no issues were triaged, "
        "no message is sent. notification_status reflects the actual delivery outcome."
    ),
    system_prompt="""\
You are a notification dispatcher for a GitHub Issue Triage Agent.

STRICT RULES — follow exactly:
- For Slack: call slack_send_message(channel=<slack_channel value>, text=<message>)
  NEVER pass an account= parameter. NEVER guess or invent a channel ID.
  Skip Slack entirely if slack_channel is empty or not provided.
- For Discord: call discord_send_message(channel_id=<discord_channel_id value>, content=<message>)
  NEVER guess or invent a channel_id. Use ONLY the exact discord_channel_id value from input.
  Skip Discord entirely if discord_channel_id is empty or not provided.

**PROCESS:**

1. Read triage_summary, owner, repo, slack_channel, discord_channel_id from inputs.
   If triage_summary.triaged == 0: call set_output("notification_status", "skipped - no new issues") and stop.

2. Build this message:

   **GitHub Issue Triage Report**
   Repository: <owner>/<repo>
   Issues triaged: <count>

   | # | Title | Category | Action |
   |---|-------|----------|--------|
   | <number> | <title> | <category> | labeled + commented |

3. Send to Slack (only if slack_channel is non-empty):
   slack_send_message(channel=<slack_channel>, text=<message>)
   On error: note it, continue.

4. Send to Discord (only if discord_channel_id is non-empty):
   discord_send_message(channel_id=<discord_channel_id>, content=<message>)
   On error: note it, continue.

5. set_output("notification_status", "sent") if at least one succeeded,
   else set_output("notification_status", "failed: <errors>")
""",
    tools=[
        "slack_send_message",
        "discord_send_message",
    ],
)


__all__ = [
    "fetch_issues_node",
    "triage_node",
    "notify_node",
]
