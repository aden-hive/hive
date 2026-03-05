"""Node definitions for GitHub Issue Triage Agent."""

from framework.graph import NodeSpec

# Node 1: Fetch Issues
# Polls GitHub for open, un-triaged issues and prepares them for classification.
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
You are a GitHub issue fetcher. Your job is to retrieve open issues that have not \
yet been triaged.

**PROCESS (follow exactly):**

**Step 1 — Load triage history:**
Call load_data(filename="triaged_issues.json") to get the list of issue numbers \
already triaged. If the file doesn't exist, treat it as an empty list [].

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
        "save_data",
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
        "Every issue in the batch has been classified with the correct label applied "
        "via github_update_issue. A triage comment has been posted on each issue. "
        "Triaged issue numbers have been persisted to triaged_issues.json."
    ),
    system_prompt="""\
You are a GitHub issue triage specialist. For each issue in the batch, classify it \
and take the appropriate action.

**If issue_count is 0, skip triage and immediately call:**
- set_output("triage_summary", {"triaged": 0, "categories": {}, "message": \
"No new issues to triage."})

**CLASSIFICATION RULES:**

| Category       | Label to apply | Action                                              |
|----------------|---------------|------------------------------------------------------|
| Bug report     | bug           | Acknowledge, ask for repro steps if missing          |
| Feature request| enhancement   | Acknowledge, note it for team review                 |
| Question       | question      | Acknowledge, suggest relevant docs if possible       |
| Duplicate      | duplicate     | Reference the original issue, close with state="closed" |
| Invalid        | invalid       | Politely explain why, close with state="closed"      |
| Needs more info| needs-triage  | Ask reporter for missing details                     |

**PROCESS for each issue:**

1. **Read** the issue title and body carefully
2. **Classify** into one of the categories above
3. **Apply label** via github_update_issue(owner, repo, issue_number, labels=[<label>])
4. **Post comment** — compose a brief, polite triage comment and include it by \
updating the issue body (append a "## Triage Notes" section) via github_update_issue. \
Be professional and helpful.
5. **Close if needed** — for duplicates and invalid issues only, also set \
state="closed" in the update call.

**CONSTRAINTS:**
- NEVER auto-close bug reports or feature requests
- Be polite and professional in all comments
- If unsure about classification, use "needs-triage" label
- Process issues in batches of 5 to respect rate limits

**After processing all issues:**

1. Load existing triaged list: load_data(filename="triaged_issues.json")
2. Append the newly triaged issue numbers
3. Save updated list: save_data(filename="triaged_issues.json", data=<updated list>)
4. Call set_output("triage_summary", {
     "triaged": <count>,
     "categories": {"bug": N, "enhancement": N, "question": N, ...},
     "issues": [{"number": N, "title": "...", "category": "...", "action": "..."}]
   })
""",
    tools=[
        "github_update_issue",
        "github_get_issue",
        "load_data",
        "save_data",
        "append_data",
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
    input_keys=["triage_summary"],
    output_keys=["notification_status"],
    success_criteria=(
        "A triage summary notification has been sent to the configured "
        "Slack channel and/or Discord channel. If no issues were triaged, "
        "a brief 'no new issues' message is sent instead."
    ),
    system_prompt="""\
You are a notification dispatcher. Send the triage summary to the team's \
communication channels.

**PROCESS:**

1. Read the triage_summary input
2. Format a clear, scannable notification message:

   **GitHub Issue Triage Report**
   Repository: {owner}/{repo}
   Issues triaged: {count}

   | # | Title | Category | Action |
   |---|-------|----------|--------|
   | ... | ... | ... | ... |

   If 0 issues were triaged, send: "✅ No new issues to triage in {owner}/{repo}."

3. Send to Slack via slack_send_message(channel=<configured channel>, text=<message>)
   - If Slack is not configured or fails, log the error and continue

4. Send to Discord via discord_send_message(channel_id=<configured channel>, \
content=<message>)
   - If Discord is not configured or fails, log the error and continue

5. Call set_output("notification_status", "sent") — even if one channel failed, \
as long as at least one notification was attempted.

**If BOTH Slack and Discord are unconfigured:**
- set_output("notification_status", "skipped — no channels configured")
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
