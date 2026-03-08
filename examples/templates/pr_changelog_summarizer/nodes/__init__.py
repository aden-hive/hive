"""Node definitions for PR Changelog Summarizer agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collect repo URL and optional PR scope from the user.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect the GitHub repository URL and optional PR scope from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["repo_owner", "repo_name", "pr_state", "pr_limit"],
    success_criteria=(
        "The user has provided a valid GitHub repo (URL or owner/repo) and "
        "optionally the PR state and limit."
    ),
    system_prompt="""\
You are the intake specialist for a PR Changelog Summarizer agent.

**STEP 1 — Greet and collect (text only, NO tool calls):**
1. Ask the user for the GitHub repository they want to summarize.
   Accept: full URL (https://github.com/owner/repo) or owner/repo format.
2. Optionally ask:
   - PR state: "merged", "closed", "all", or "open" (default: "closed" for release notes)
   - Limit: how many PRs to include (default: 20, max 50)
3. If the user already provided a repo in their message, confirm it and ask about scope.
4. Keep it brief — 1-2 questions max.

**STEP 2 — After the user responds, call set_output:**
Parse the repo and set:
- set_output("repo_owner", "owner from URL or owner/repo")
- set_output("repo_name", "repo name from URL or owner/repo")
- set_output("pr_state", "merged" or "closed" or "all" or "open" — default "closed")
- set_output("pr_limit", "20" or user's number, as string, max 50)
""",
    tools=[],
)

# Node 2: Fetch PRs
# Use GitHub tools to list and fetch PR details.
fetch_node = NodeSpec(
    id="fetch",
    name="Fetch PRs",
    description="List pull requests from the repo and fetch details for summarization",
    node_type="event_loop",
    max_node_visits=1,
    input_keys=["repo_owner", "repo_name", "pr_state", "pr_limit"],
    output_keys=["prs_data"],
    success_criteria=(
        "PRs have been fetched and summarized with title, number, author, "
        "merged/closed date, and a brief description."
    ),
    system_prompt="""\
You are a PR fetcher for a changelog summarizer.

Given repo_owner, repo_name, pr_state, and pr_limit from the intake:

1. **List PRs**: Call github_list_pull_requests(owner=repo_owner, repo=repo_name, state=pr_state, limit=pr_limit)
   - state: "open", "closed", or "all"
   - limit: integer from pr_limit (default 20, max 50)

2. **Fetch details**: For each PR in the list (or the first N up to limit), call github_get_pull_request
   to get the full body/description. This helps produce better changelog entries.

3. **Structure the output**: Build a JSON object with:
   - repo: {owner, name}
   - generated_at: ISO date
   - prs: array of {number, title, author, state, merged_at/closed_at, body_summary, url}
   - Group by category if possible (features, fixes, docs, etc.) based on labels or title prefixes

4. **Call set_output**:
   set_output("prs_data", "<JSON string of the structured PR data>")

**Rules:**
- Only include PRs you actually fetched — never fabricate
- If github_list_pull_requests returns an error (e.g. 404, private repo), set_output with an error
  message in prs_data so the report node can inform the user
- Keep body_summary to 1-2 sentences per PR
- Batch github_get_pull_request calls — do 3-5 per turn to avoid rate limits
""",
    tools=[
        "github_list_pull_requests",
        "github_get_pull_request",
        "save_data",
        "load_data",
        "list_data_files",
    ],
)

# Node 3: Report (client-facing)
# Generate changelog and deliver to user.
report_node = NodeSpec(
    id="report",
    name="Generate Changelog",
    description="Generate a formatted changelog from PR data and deliver to the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["prs_data", "repo_owner", "repo_name"],
    output_keys=["delivery_status"],
    success_criteria=(
        "A changelog file has been saved and the user has received a clickable link."
    ),
    system_prompt="""\
You are the report generator for a PR Changelog Summarizer.

**If prs_data contains an error** (e.g. "error": "Not found" or "Repository not found"):
- Present the error to the user clearly
- Suggest: check the repo URL, ensure it's public, or verify GitHub credentials
- set_output("delivery_status", "error")

**Otherwise, generate the changelog:**

1. **Parse prs_data** — it's a JSON string with repo info and prs array.

2. **Build the changelog** in Markdown format:
   - Title: "Changelog: {owner}/{repo}"
   - Date generated
   - Sections: "Features", "Bug Fixes", "Documentation", "Other" (categorize by labels or title)
   - Each PR: "- [#N] Title (by @author) — brief summary"
   - Include links to each PR

3. **Save and serve**:
   - save_data(filename="CHANGELOG.md", data="<markdown content>")
   - serve_file_to_user(filename="CHANGELOG.md", label="Changelog")
   - Do NOT pass data_dir — it is auto-injected by the framework

4. **Present to user** (text only):
   - Summarize: "Generated changelog with X PRs from {owner}/{repo}"
   - Include the file path from serve_file_to_user so they can click to open
   - set_output("delivery_status", "completed")

**IMPORTANT:** save_data and serve_file_to_user take (filename, data) and (filename, label) —
the data_dir parameter is injected by the framework, do not include it in your tool calls.
""",
    tools=[
        "save_data",
        "serve_file_to_user",
        "load_data",
        "list_data_files",
    ],
)

__all__ = [
    "intake_node",
    "fetch_node",
    "report_node",
]
