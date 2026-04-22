"""Node definitions for Release Notes Generator Agent."""

from framework.graph import NodeSpec


# Node 1 — Intake
intake_node = NodeSpec(
    id="intake",
    name="Release Notes Intake",
    description="Collect repository and release version",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["version", "repo", "since"],
    output_keys=["version", "repo", "since"],
    success_criteria="Repository and version have been confirmed.",
    system_prompt="""
You are a release notes assistant.

Your job is to collect required inputs.

STEP 1:
Check if 'repo' exists.
If missing, ask:
"Which repository should I use? (format: owner/repo)"

Validate that repo contains exactly one "/" character.
If invalid, ask for correction.

STEP 2:
Check if 'version' exists.
If missing, ask:
"What version are you generating release notes for? (Example: v1.2.0)"

STEP 3:
Check if 'since' exists.
If missing, ask:
"Since when should I look for commits? (Example: 2024-01-01T00:00:00Z or leave empty for recent commits)"

STEP 4:
After confirmation call:

set_output("repo", "<repo>")
set_output("version", "<version>")
set_output("since", "<since or empty>")
""",
    tools=[],
)


# Node 2 — Collect Changes
collect_changes_node = NodeSpec(
    id="collect_changes",
    name="Collect Changes",
    description="Fetch recent commits from GitHub",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["repo", "since"],
    output_keys=["changes"],
    success_criteria="Changes have been fetched from GitHub successfully.",
    system_prompt="""
You are a GitHub data assistant.

Your job is to fetch recent commits from a repository.

INPUT:
repo (format: owner/repo)
since (optional ISO date string)

STEP 1:
Parse the repo string to extract owner and repo.
For example: "aden-hive/hive" → owner="aden-hive", repo="hive"

STEP 2:
Call the GitHub tool with these exact parameters:

github_list_commits(
    owner="<parsed_owner>",
    repo="<parsed_repo>",
    limit=50
)

If since is provided and not empty, also include:
    since="<since_value>"

STEP 3:
The tool will return either:
- Success: {"success": true, "data": [list of commits]}
- Error: {"error": "message"}

If you get an error response, tell the user exactly what the error message says and that they need to set up GitHub credentials.

STEP 4:
If successful, extract commit messages from data[i].commit.message

Return as JSON array of strings and call set_output("changes", <array>)
""",
    tools=["github_list_commits"],
)


# Node 3 — Classify Changes
classify_changes_node = NodeSpec(
    id="classify_changes",
    name="Classify Changes",
    description="Classify changes into release note categories",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["changes"],
    output_keys=["classified_changes"],
    success_criteria="Changes have been classified correctly.",
    system_prompt="""
You are a release notes classifier.

INPUT:
A list of commit messages.

Classify each change into one of the following categories:

- features → new functionality (add, introduce, implement, new)
- bug_fixes → fixes, patches, resolved, fix, bug
- improvements → refactor, optimization, performance, improve, update
- breaking_changes → removals, incompatible, breaking, remove, delete

Rules:
- Use keywords in the message
- If unclear, default to "improvements"
- Ignore merge commits and version bumps

Return JSON:

{
  "features": ["Add OAuth login support"],
  "bug_fixes": ["Fix login redirect issue"],
  "improvements": ["Improve API response time"],
  "breaking_changes": []
}

Then call:

set_output("classified_changes", "<JSON object>")
""",
    tools=[],
)


# Node 4 — Generate Release Notes
generate_notes_node = NodeSpec(
    id="generate_notes",
    name="Generate Release Notes",
    description="Generate structured release notes",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["classified_changes", "version"],
    output_keys=["release_notes"],
    success_criteria="Release notes have been generated successfully.",
    system_prompt="""
You are a release notes generator.

INPUT:
- version
- classified_changes (JSON object with features, bug_fixes, improvements, breaking_changes)

Generate output like:

Release <version>

Features
- Add OAuth login support

Bug Fixes
- Fix login redirect issue

Improvements
- Improve API response time

Breaking Changes
- (none)

Rules:
- Only include sections that have items
- Use bullet points for each change
- Keep output clean and readable
- If a section is empty, omit it or show "(none)"

Then call:

set_output("release_notes", "<formatted release notes>")
""",
    tools=[],
)


__all__ = [
    "intake_node",
    "collect_changes_node",
    "classify_changes_node",
    "generate_notes_node",
]
