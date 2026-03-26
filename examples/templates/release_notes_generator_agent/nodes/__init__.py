"""Node definitions for Release Notes Generator Agent."""

from framework.graph import NodeSpec


# Node 1 — Intake
intake_node = NodeSpec(
    id="intake",
    name="Release Notes Intake",
    description="Collect release version for generating release notes",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["version"],
    output_keys=["version"],
    success_criteria="Release version has been confirmed.",
    system_prompt="""
You are a release notes assistant.

Your job is to collect the release version.

STEP 1:
Check if 'version' exists.

If missing, ask:
"What version are you generating release notes for? (Example: v1.2.0)"

STEP 2:
After confirmation call:

set_output("version", "<version>")
""",
    tools=[],
)


# Node 2 — Collect Changes
collect_changes_node = NodeSpec(
    id="collect_changes",
    name="Collect Changes",
    description="Collect recent commit messages or PR titles",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=[],
    output_keys=["changes"],
    success_criteria="Changes have been collected successfully.",
    system_prompt="""
You are responsible for collecting recent changes.

For now, simulate realistic commit messages or pull request titles.

Examples:
- "Add OAuth login support"
- "Fix login redirect bug"
- "Improve API response time"
- "Refactor authentication module"
- "Add user analytics dashboard"

Return a JSON list of changes.

Then call:

set_output("changes", "<JSON list of changes>")
""",
    tools=[],
)


# Node 3 — Classify Changes
classify_changes_node = NodeSpec(
    id="classify_changes",
    name="Classify Changes",
    description="Classify changes into categories",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["changes"],
    output_keys=["classified_changes"],
    success_criteria="Changes have been classified correctly.",
    system_prompt="""
You are a release notes classifier.

INPUT:
changes = list of changes

Classify each change into one of the following:
- features
- bug_fixes
- improvements
- breaking_changes

Return JSON in this format:

{
  "features": [],
  "bug_fixes": [],
  "improvements": [],
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
    description="Generate formatted release notes",
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
- classified_changes

Generate structured release notes in this format:

Release <version>

Features
- ...

Bug Fixes
- ...

Improvements
- ...

Breaking Changes
- ...

Rules:
- Only include sections that have items
- Keep formatting clean and readable

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
