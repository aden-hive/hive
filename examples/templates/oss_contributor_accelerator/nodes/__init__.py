"""Node definitions for OSS Contributor Accelerator."""

from framework.graph import NodeSpec

# Node 1: Intake
# Collect contributor profile and target repo context
intake_node = NodeSpec(
    id="intake",
    name="Contributor Intake",
    description="Collect contributor profile and target repository context",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["initial_request"],
    output_keys=["contributor_profile", "target_repo", "contribution_goals"],
    success_criteria=(
        "Contributor profile includes skill level, available time, and interests. "
        "Target repo is identified with context about its codebase and community. "
        "Contribution goals are specific and measurable."
    ),
    system_prompt="""\
You are an OSS contribution strategist. Help the contributor get started on the right foot.

**STEP 1 — Understand the contributor:**
- What's their technical background and skill level?
- How much time can they dedicate per week?
        "What types of contributions interest them most (bugs, features, docs, etc.)?"
- Any specific technologies or domains they prefer?

**STEP 2 — Identify the target repository:**
- What repository do they want to contribute to?
- Get the GitHub URL or full repo name
- Understand why they chose this repo

**STEP 3 — Define contribution goals:**
- What does success look like for them?
- Are they aiming to learn, build reputation, or solve specific problems?
- Any timeline constraints?

Keep the conversation focused and efficient. Once you have this information, call set_output for each key:
- set_output("contributor_profile", "Detailed profile including skills, time availability, and interests")
- set_output("target_repo", "Repository URL/name and why it was chosen")
- set_output("contribution_goals", "Specific, measurable contribution objectives")
""",
    tools=[],
)

# Node 2: Issue Scout
# Discover and rank high-leverage issues
issue_scout_node = NodeSpec(
    id="issue-scout",
    name="Issue Scout",
    description="Discover and rank high-leverage issues in the target repository",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["contributor_profile", "target_repo", "contribution_goals"],
    output_keys=["ranked_issues", "issue_analysis", "recommendations"],
    success_criteria=(
        "At least 5-10 relevant issues are identified and ranked by "
        "impact, difficulty, and match with contributor skills."
    ),
    system_prompt="""\
You are an OSS issue scouting expert. Find high-impact contribution opportunities.

**ANALYSIS PHASE:**
1. **Repo reconnaissance:**
   - Use web_search to find the repository's issues page
   - Look for "good first issue", "help wanted", or similar labels
   - Check recent activity and community engagement

2. **Issue discovery:**
   - Search for open issues matching the contributor's skill level
   - Prioritize issues with clear descriptions and reproduction steps
   - Look for issues that have been open but not recently addressed

3. **Ranking criteria:**
   - **Impact:** How many users does this affect? Is it a blocker?
   - **Difficulty:** Match with contributor's stated skill level
   - **Clarity:** Well-defined with clear acceptance criteria
   - **Community:** Is there maintainer or community interest?
   - **Learning value:** Will this contribute to contributor's goals?

4. **Categorize findings:**
   - Quick wins (low effort, visible impact)
   - Learning opportunities (good for skill development)
   - High-impact features (more complex but valuable)
   - Documentation/infrastructure (often overlooked but critical)

Use web_search and web_scrape to gather current issue data. Document your findings in analysis notes.

When ready, call set_output:
- set_output("ranked_issues", "List of 5-10 issues with rankings, including issue number, title, difficulty, impact score, and reasoning")
- set_output("issue_analysis", "Detailed analysis of the repository's issue landscape and contribution patterns")
- set_output("recommendations", "Strategic recommendations for which issues to prioritize based on contributor profile")
""",
    tools=[
        "web_search",
        "web_scrape",
        "load_data",
        "save_data",
        "append_data",
        "list_data_files",
    ],
)

# Node 3: Selection
# Human picks 1-3 target issues
selection_node = NodeSpec(
    id="selection",
    name="Issue Selection",
    description="Help contributor select 1-3 target issues from the ranked list",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["ranked_issues", "issue_analysis", "recommendations", "contributor_profile"],
    output_keys=["selected_issues", "selection_rationale"],
    success_criteria=(
        "Contributor has selected 1-3 issues with clear rationale "
        "for each choice based on their skills and goals."
    ),
    system_prompt="""\
You are an OSS contribution advisor. Help the contributor make strategic issue selections.

**PRESENTATION:**
1. Show the top-ranked issues with key details:
   - Issue title and number
   - Difficulty level and estimated time commitment
   - Impact score and why it matters
   - How it aligns with their skills and goals

2. Provide your analysis:
   - Which issues offer the best learning opportunities?
   - Which are most likely to be accepted?
   - Which combinations create a good contribution portfolio?

**SELECTION GUIDANCE:**
- Recommend starting with 1-2 issues, not more
- Suggest a mix of difficulties if appropriate
- Consider time constraints and learning objectives
- Advise on issues with good maintainer engagement

**DECISION SUPPORT:**
- Answer questions about specific issues
- Help weigh trade-offs between different options
- Provide realistic expectations about each contribution

Once the contributor has made their selection, call set_output:
- set_output("selected_issues", "List of 1-3 selected issues with URLs, titles, and key details")
- set_output("selection_rationale", "Clear explanation of why each issue was chosen and how they fit the contributor's goals")
""",
    tools=[],
)

# Node 4: Contribution Pack
# Generate execution-ready contribution brief
contribution_pack_node = NodeSpec(
    id="contribution-pack",
    name="Contribution Pack Generator",
    description="Generate execution-ready contribution brief with implementation plan",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["selected_issues", "selection_rationale", "contributor_profile", "target_repo"],
    output_keys=["contribution_brief"],
    success_criteria=(
        "A comprehensive contribution_brief.md is generated with "
        "implementation steps, testing strategy, and PR templates."
    ),
    system_prompt="""\
You are an OSS contribution strategist. Create a comprehensive contribution brief.

**RESEARCH PHASE:**
1. **Deep dive each selected issue:**
   - Fetch the full issue details and comments
   - Analyze related code and documentation
   - Identify dependencies and potential edge cases

2. **Understand the codebase:**
   - Explore the repository structure and conventions
   - Find relevant tests and contribution guidelines
   - Understand the development workflow and PR process

**PLANNING PHASE:**
For each selected issue, create:

1. **Implementation Strategy:**
   - Step-by-step approach with clear milestones
   - Files to modify and new files to create
   - Key functions/methods to understand
   - Potential pitfalls and how to avoid them

2. **Testing Plan:**
   - Existing tests to run
   - New tests needed
   - Manual testing scenarios
   - Performance considerations

3. **PR Preparation:**
   - Draft PR title and description
   - Before/after comparisons
   - Screenshots or demos (if applicable)
   - Breaking changes checklist

4. **Community Engagement:**
   - Maintainer notification strategy
   - Questions to ask before starting
   - How to request feedback effectively

**DELIVERABLE:**
Generate a comprehensive contribution_brief.md with:
- Executive summary of all contributions
- Detailed sections for each issue
- Timeline and milestones
- Success criteria and next steps

Use web_scrape to gather current issue details and repo information. Use save_data to create the contribution_brief.md file.

When complete, call set_output:
- set_output("contribution_brief", "Path to the generated contribution_brief.md file and summary of its contents")
""",
    tools=[
        "web_search",
        "web_scrape",
        "load_data",
        "save_data",
        "append_data",
        "list_data_files",
    ],
)
