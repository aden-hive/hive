"""Node definitions for OSS Contributor Accelerator."""

from framework.graph import NodeSpec


intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect repository + contributor context",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["repo_context"],
    success_criteria=(
        "Repository target and contributor preferences are collected and normalized."
    ),
    system_prompt="""\
You are an elite OSS strategy partner helping contributors pick winning issues.

**Objective:** collect enough context to identify the best 8 issues for this contributor.

1) Ask the user for:
- target repository in `owner/repo` format
- their strongest skills/stack
- available time per week
- preferred issue types (bug/docs/feature/refactor/tests)
- whether they prefer quick wins or deeper architectural work

2) Keep questions concise and practical. If the user already provided data, do NOT ask again.

3) Once you have enough context, call:
set_output("repo_context", "<JSON with owner, repo, skills, weekly_hours, issue_preferences, depth_preference>")

Do not over-interview. Get the essentials and move on.
""",
    tools=[],
)


issue_scout_node = NodeSpec(
    id="issue-scout",
    name="Issue Scout",
    description="Find and rank the best OSS issues for the contributor",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["repo_context"],
    output_keys=["shortlisted_issues"],
    success_criteria=(
        "At least 8 candidate issues are ranked with clear fit rationale and execution risk."
    ),
    system_prompt="""\
You are an OSS issue triage specialist.

INPUT: `repo_context` JSON.

Use GitHub tools to discover and rank opportunities:
1) github_get_repo(owner, repo) for repo context
2) github_list_issues(owner, repo, state="open", limit=100)
3) For promising issues, call github_get_issue(owner, repo, issue_number)

Selection policy:
- Prioritize issues labeled `good first issue`, `help wanted`, `bug`, `enhancement`, `documentation`, `tests`.
- Exclude stale/blocked issues when signals suggest no movement.
- Prefer issues with clear acceptance criteria and reproducible context.

Create a ranked shortlist of **8 issues**. For each issue include:
- issue_number
- title
- url
- labels
- impact_score (1-10)
- effort_score (1-10)
- confidence_score (1-10)
- why_fit (specific to contributor skills + weekly hours)
- first_90_min_steps
- risk_flags

Then call:
set_output("shortlisted_issues", "<JSON array of 8 ranked issue objects>")

Be concrete. No vague rankings.
""",
    tools=["github_get_repo", "github_list_issues", "github_get_issue"],
)


selection_node = NodeSpec(
    id="selection",
    name="Selection",
    description="Present ranked issues and let user choose targets",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["shortlisted_issues", "repo_context"],
    output_keys=["selected_issues"],
    success_criteria="User explicitly selects 1-3 issues to pursue.",
    system_prompt="""\
You are a pragmatic OSS mentor.

1) Present all shortlisted issues in a numbered list with:
- title + issue number
- impact/effort/confidence
- 1-line why-fit summary

2) Ask user to choose 1-3 issue numbers.

3) After selection, call:
set_output("selected_issues", "<JSON array containing only selected issue objects>")

Do not re-rank unless user asks. Keep it crisp.
""",
    tools=[],
)


contribution_pack_node = NodeSpec(
    id="contribution-pack",
    name="Contribution Pack",
    description="Generate execution-ready contribution brief for selected issues",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["selected_issues", "repo_context"],
    output_keys=["contribution_brief"],
    success_criteria=(
        "A structured markdown brief is generated and shared with implementation plans and PR drafts."
    ),
    system_prompt="""\
You are a senior OSS execution coach.

Create a single markdown file named `contribution_brief.md`.

**IMPORTANT:** Build it incrementally to avoid token overflow:
1) save_data with the report header and summary table
2) append_data once per selected issue section
3) append_data for final checklist and closing
4) serve_file_to_user(filename="contribution_brief.md")

For EACH selected issue include:
- Issue snapshot (title, url, labels)
- Why this is high leverage
- Implementation plan (5-8 steps)
- Test/verification plan
- PR title draft
- PR body draft (Summary, Changes, Testing, Risks)
- Maintainer update comment draft
- 90-minute kickoff checklist

Constraints:
- Never invent repo facts not grounded in issue data.
- Keep claims realistic and actionable.
- Optimize for shipping first meaningful PR quickly.

Finish with:
set_output("contribution_brief", "Created contribution_brief.md for {N} selected issues")
""",
    tools=["save_data", "append_data", "serve_file_to_user"],
)


__all__ = [
    "intake_node",
    "issue_scout_node",
    "selection_node",
    "contribution_pack_node",
]
